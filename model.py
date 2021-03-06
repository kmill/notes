import os.path
import time
import sqlite3
import json
import datetime

DB = None

def db_connect(dbfile) :
    """Connects to the db.  Sets the global DB variable because there should be only
    one connection to the db at a time anyway."""
    global DB
    if not os.path.isfile(dbfile) :
        raise TypeError("The database file must be created first.")
    DB = sqlite3.connect(dbfile, detect_types=sqlite3.PARSE_DECLTYPES)
    DB.executescript("""
        pragma foreign_keys = ON;
    """)
    DB.row_factory = sqlite3.Row

class User(object) :
    def __init__(self, id=None, email=None, name=None, extra_data=None) :
        self.id = id
        self.email = email
        self.name = name
        self.extra_data = extra_data
    def update(self) :
        if self.id == None :
            with DB :
                c = DB.execute("insert into users (email, name, extra_data) values (?,?,?)",
                               (self.email,self.name,self.extra_data))
                self.id = c.lastrowid
        else :
            with DB :
                DB.execute("update users set name=?, extra_data=? where id=?",
                           (self.name, self.extra_data, self.id))
    @classmethod
    def ensure(cls, email, name=None) :
        u = cls.with_email(email)
        if u == None :
            u = User(email=email, name=name)
            u.update()
        return u
    @classmethod
    def with_email(cls, email) :
        for row in DB.execute("select id, email, name from users where email=?", (email,)) :
            return User(id=row['id'], email=row['email'], name=row['name'])
    @classmethod
    def with_id(cls, id) :
        for row in DB.execute("select id, email, name from users where id=?", (id,)) :
            return User(id=row['id'], email=row['email'], name=row['name'])


class Wiki(object) :
    def __init__(self, id=None, name=None) :
        self.id = id
        self.name = name

    def add_user(self, user) :
        with DB :
            DB.execute("insert into user_wiki (user_id, wiki_id) values (?,?)",
                       (user.id, self.id))

    def allows_user(self, user) :
        for row in DB.execute("select 1 from user_wiki where wiki_id=? and user_id=?",
                              (self.id, user.id)) :
            return True
        return False

    def document_ids(self) :
        docids = []
        for row in DB.execute("""select d.id as id, mime, v.created as modified, m.mvalue as title, uuid
                                   from documents as d join versions as v on d.version=v.id
                                         left outer join meta as m on m.docid=d.id
                                   where d.wiki=? and not deleted""", (self.id,)) :
            description = 'Doc ' + str(row['id'])
            mimes = row['mime'].split(';',1)
            if row['title'] :
                description = row['title']
            elif len(mimes) > 1 and mimes[1] != row['uuid'] :
                description = mimes[1]
            elif row['uuid'] :
                description = row['uuid']
                if mimes[0] != "text/texdown" :
                    description += " (" + mimes[0] + ")"
            docids.append({ 'id' : row['id'],
                            'title' : row['title'],
                            'mime' : row['mime'],
                            'modified' : row['modified'],
                            'description' : description })
        return docids

    @classmethod
    def ensure(cls, name) :
        w = cls.with_name(name)
        if w == None :
            with DB :
                c = DB.execute("insert into wikis (name) values (?)", (name,))
                w = Wiki(id=c.lastrowid, name=name)
        return w

    @classmethod
    def with_name(cls, name) :
        for row in DB.execute("select id, name from wikis where name=?", (name,)) :
            return Wiki(id=row['id'], name=row['name'])
    @classmethod
    def with_id(cls, id) :
        for row in DB.execute("select id, name from wikis where id=?", (id,)) :
            return Wiki(id=row['id'], name=row['name'])
    @classmethod
    def with_user(cls, user) :
        wikis = []
        for row in DB.execute("select w.id as id, w.name as name from wikis as w join user_wiki as uw on w.id=uw.wiki_id where user_id=?",
                              (user.id,)) :
            wikis.append(Wiki(id=row['id'], name=row['name']))
        return wikis

class Version(object) :
    def __init__(self, id, wiki, author, created, mime, content) :
        self.id = id
        self.wiki = wiki
        self.author = author
        self.created = created
        self.mime = mime
        self.content = content

#   def parents_ids(self) :
#       pids = []
#       for row in DB.execute("""with recursive ancestor(vid, pid, author, created) as (
#                                 select version, parent, author, created
#                                 from select version, parent from parents where 

    def parent_ids(self) :
        pids = []
        for row in DB.execute("select parent, created from parents join versions on parents.parent=versions.id where version=?", (self.id,)) :
            pids.append({'id' : row['parent'],
                         'created' : row['created']})
        return pids
    def child_ids(self) :
        pids = []
        for row in DB.execute("select version, created from parents join versions on parents.version=versions.id where parent=?", (self.id,)) :
            pids.append({'id' : row['version'],
                         'created' : row['created']})
        return pids

    def docs(self) :
        return Document.with_version(self)

    @classmethod
    def with_id(cls, wiki, id) :
        for row in DB.execute("select author, created, mime, content from versions where id=? and wiki=?", (id,wiki.id)) :
            return Version(id=id, wiki=wiki, author=User.with_id(row['author']),
                           created=row['created'], mime=row['mime'], content=row['content'])
    @classmethod
    def create(cls, wiki, author, mime, content, parents=None) :
        if parents == None :
            parents = []
        with DB :
            created = int(time.time())
            c = DB.execute("insert into versions (wiki, author, created, mime, content) values (?,?,?,?,?)",
                           (wiki.id, author.id, created, mime, content))
            v = Version(id=c.lastrowid, wiki=wiki, author=author, created=created, mime=mime, content=content)
            for parent in parents :
                if parent.wiki.id != v.wiki.id :
                    raise Exception("Cannot make a version across wikis")
                DB.execute("insert into parents (version, parent) values (?,?)", (v.id, parent.id))
            return v

class Document(object) :
    def __init__(self, id=None, uuid=None, wiki=None, version_id=None, version=None, deleted=False, temp=False) :
        self.id = id
        self.uuid = uuid
        self.wiki = wiki
        if version :
            self.version_id = version.id
            self._version = version
        else :
            self.version_id = version_id
            self._version = None
        self.deleted = deleted
        self.temp = temp

        self.meta_cache = {}

        self._init_id = self.id
        self._init_uuid = self.uuid
        self._init_version_id = self.version_id
        self._init_deleted = self.deleted

    def describe_change(self) :
        if self.id != self._init_id :
            return "created"
        elif self._init_version_id != self.version_id :
            return "modified"
        elif self._init_deleted != self.deleted :
            return "deleted" if self.deleted else "undeleted"
        elif self._init_uuid != self.uuid :
            return "uuid"
        else :
            return "no change"

    def describe(self) :
        title = self.get_meta('title')
        if title :
            return title
        mime = self.version.mime.split(';',1)
        prefix = self.uuid or ('Doc ' + str(self.id))
        if mime[0] != 'text/texdown' :
            if len(mime) > 1 :
                return mime[1]
            else :
                return prefix + '(' + self.mime[0] + ')'
        return prefix

    @property
    def version(self) :
        if not self._version :
            self._version = Version.with_id(self.wiki, self.version_id)
        return self._version            
    @version.setter
    def version(self, value) :
        self.version_id = value.id
        self._version = value

    def update(self) :
        if self.temp :
            raise Exception("Saving temp document")
        if self.id == None :
            with DB :
                c = DB.execute("insert into documents (uuid, wiki, version, deleted) values (?,?,?,?)",
                               (self.uuid, self.wiki.id, self.version.id, self.deleted))
                self.id = c.lastrowid
        else :
            with DB :
                DB.execute("update documents set uuid=?, version=?, deleted=? where id=?",
                           (self.uuid, self.version.id, self.deleted, self.id))
        with DB :
            DB.execute("insert into changes (changed, docid, version, description) values (?,?,?,?)",
                       (int(time.time()), self.id, self.version.id, self.describe_change()))
        self._init_id = self.id
        self._init_version_id = self.version_id
        self._init_deleted = self.deleted

    def update_meta(self, kvs) :
        with DB :
            DB.execute("delete from meta where docid=?", (self.id,))
            for k, v in kvs.iteritems() :
                DB.execute("insert into meta (docid, mkey, mvalue) values (?,?,?)",
                           (self.id, k, v))

    def update_links(self, links) :
        with DB :
            DB.execute("delete from links where docid=?", (self.id,))
            for link in links :
                DB.execute("insert into links (docid, link) values (?,?)",
                           (self.id, link))

    def get_meta(self, key) :
        try :
            return self.meta_cache[key]
        except KeyError :
            for row in DB.execute("select mvalue from meta where docid=?", (self.id,)) :
                v = self.meta_cache[key] = row['mvalue']
                return v
            return None

    @classmethod
    def with_id(cls, wiki, id) :
        for row in DB.execute("select uuid, version, deleted from documents where id=? and wiki=?",
                              (id, wiki.id)) :
            return Document(id=id, uuid=row['uuid'], wiki=wiki, version_id=row['version'],
                            deleted=bool(row['deleted']))

    @classmethod
    def with_uuid(cls, wiki, uuid) :
        for row in DB.execute("select id, version, deleted from documents where uuid=? and wiki=?",
                              (uuid, wiki.id)) :
            return Document(id=row['id'], uuid=uuid, wiki=wiki, version_id=row['version'],
                            deleted=bool(row['deleted']))


    @classmethod
    def with_version(cls, version) :
        docs = []
        for row in DB.execute("select id, uuid, deleted from documents where version=? and wiki=?",
                              (version.id, version.wiki.id)) :
            docs.append(Document(id=row['id'], uuid=row['uuid'], wiki=version.wiki, version=version, deleted=bool(row['deleted'])))
        return docs

    @classmethod
    def titles(cls, wiki) :
        titles = set()
        for row in DB.execute("select mvalue from meta join documents on meta.docid=documents.id where mkey='title' and wiki=? and not deleted", (wiki.id,)) :
            titles.add(row['mvalue'])
        return titles

    @classmethod
    def search(cls, wiki, query) :
        docs = []
        for row in DB.execute("select id, uuid, deleted, version from documents where not deleted and wiki=?", (wiki.id,)) :
            doc = Document(id=row['id'], uuid=row['uuid'], wiki=wiki, version_id=row['version'])
            v = doc.version
            if v.mime == "text/texdown" and query(v.content.lower()) :
                docs.append(doc)
        return docs

class Links(object) :
    @staticmethod
    def links_to(wiki, title) :
        docs = []
        for row in DB.execute("select docid from links where link=?", (title,)) :
            docs.append(Document.with_id(wiki, row['docid']))
        return docs

class Changes(object) :
    @staticmethod
    def changes(wiki, n, offset=0, newest=False) :
        changes = []
        if not newest :
            res = DB.execute("""select c.changed, c.docid, c.version, c.description, v.mime
                                 from changes as c join documents as d on c.docid = d.id
                                   join versions as v on c.version=v.id
                                 where d.wiki=?
                                 order by changed desc limit ? offset ? """, (wiki.id, n, offset))
        else :
            res = DB.execute("""select c.changed, c.docid, c.version, c.description, v.mime
                                 from changes as c join documents as d on c.docid = d.id
                                   join versions as v on c.version=v.id
                                 where d.wiki=? and d.version=v.id and c.description in ('modified', 'created', 'undeleted') and not d.deleted
                                 order by changed desc limit ? offset ?""", (wiki.id, n, offset))
        for row in res :
            doc = Document.with_id(wiki, row['docid'])

            desc = 'Doc ' + str(doc.id)
            mimes = row['mime'].split(';',1)
            if doc.get_meta('title') :
                desc = doc.get_meta('title')
            elif len(mimes) > 1 and mimes[1] != doc.uuid :
                desc = mimes[1]
            elif doc.uuid :
                desc = doc.uuid
                if mimes[0] != "text/texdown" :
                    desc += " (" + mimes[0] + ")"

            changes.append({
                    'changed' : row['changed'],
                    'doc' : doc,
                    'version' : row['version'],
                    'description' : row['description'],
                    'shortdesc' : desc
                    })
        return changes
