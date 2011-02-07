"""
Module to be used to upload to the PALFA common database.

Patrick Lazarus, Jan. 12, 2011
"""
import sys
import atexit
import warnings

import database


# A global dictionary to keep track of database connections
db_connections = {}
            

@atexit.register # register this function to be executed at exit time
def close_db_connections():
    """A function to close database connections at exit time.
    """
    for db in db_connections.values():
        db.close()


class Uploadable(object):
    """An object to support basic operations for uploading
        to the PALFA commonDB using SPROCs.
    """
    def get_upload_sproc_call(self):
        raise NotImplementedError("get_upload_sproc_call() should be defined by a " \
                                  "subclass of Uploadable.")
    
    def upload(self, dbname='common-copy'):
        """Upload an Uploadable to the desired database.
        """
        warnings.warn("Default is to connect to common-copy DB at Cornell for testing...")
        if dbname not in db_connections:
            try:
                db_connections[dbname] = database.Database(dbname)
            except:
                raise UploadError("There was an error establishing a connection " \
                                    "to %s" % dbname)
        db = db_connections[dbname]
        query = str(self.get_upload_sproc_call())
        db.cursor.execute(query)
        try:
            db.cursor.execute(query)
        except:
            raise UploadError("There was an error executing the following " \
                                "query: %s" % query)
        try:
            result = db.cursor.fetchone()[0]
        except:
            raise UploadError("There was an error fetching the result of " \
                                "the following query: %s" % query)
        return result

    def __str__(self):
        s = self.get_upload_sproc_call()
        return s.replace('@', '\n    @')
 

class UploadError(Exception):
    """An error to do with uploading to the PALFA common DB.
        In most instances, this error will wrap an error thrown
        by pyodbc.
    """
    def __init__(self, *args):
        super(UploadError, self).__init__(self, *args)
        self.orig_exc = sys.exc_info() # The exception being wrapped, if any
