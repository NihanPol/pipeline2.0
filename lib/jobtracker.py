import sqlite3
import time
import datetime
import types

import config.background


def nowstr():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def query(queries, fetchone=False):
    """Execute multiple queries to the sqlite3 jobtracker database.
        All queries will be executed as a single transaction.
        Return the result of the last query, or the ID of the last
        INSERT, whichever is applicaple.

        Inputs:
            queries: A list of queries to be execute.
            fetchone: If True, fetch and return only a single row.
                        Otherwise, fetch and return all rows.
                        (Only applies for SELECT statements.
                        Default: fetch all rows).

        Outputs:
            results: Single row, or list of rows (for SELECT statements),
                        depending on 'fetchone'. Or, the ID of the last
                        entry INSERT'ed (for INSERT statements).
    """
    if isinstance(queries, (types.StringType, types.UnicodeType)):
        # Make a list if only a single string is pass in
        queries = [queries]
    not_connected = True
    count = 0
    while not_connected:
        try:
            db_conn = sqlite3.connect(config.background.jobtracker_db,timeout=40.0)
            db_conn.isolation_level = 'DEFERRED'
            db_conn.row_factory = sqlite3.Row
            db_cur = db_conn.cursor()
            for q in queries:
                db_cur.execute(q)
            db_conn.commit()
            if db_cur.lastrowid:
                results = db_cur.lastrowid
            else:
                if fetchone:
                    results = db_cur.fetchone()
                else:
                    results = db_cur.fetchall()
            db_conn.close()
            not_connected = False
        except sqlite3.OperationalError, e:
            try:
                db_conn.rollback()
                db_conn.close()
            except NameError:
                # Connection wasn't established, 'db_conn' is not defined.
                pass
            if count > 59:
                print "Couldn't connect to DB for 1 minute. Will continue trying. " \
                        "Error message: %s" % str(e)
                count = 0
            time.sleep(1)
            count+=1
    return results

