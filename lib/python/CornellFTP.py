import os
import os.path

import M2Crypto
import mailer
import OutStream
import config.basic
import config.background
import config.download

cout = OutStream.OutStream("CornellFTP Module", \
                os.path.join(config.basic.log_dir, "downloader.log"), \
                config.background.screen_output)

class CornellFTP(M2Crypto.ftpslib.FTP_TLS):
    def __init__(self, host=config.download.ftp_host, \
                        port=config.download.ftp_port, \
                        username=config.download.ftp_username, \
                        password=config.download.ftp_password, \
                        *args, **kwargs):

        M2Crypto.ftpslib.FTP_TLS.__init__(self, *args, **kwargs)
        try:
            self.connect(host, port)
            self.auth_tls()
            self.set_pasv(1)
            self.login(username, password)
        except Exception, e:
            raise CornellFTPError(str(e))
        else:
            cout.outs("CornellFTP - Connected and logged in")

    def __del__(self):
        if self.sock is not None:
            self.quit()

    def list_files(self, ftp_path):
        return self.nlst(ftp_path)

    def get_files(self, ftp_path):
        files = self.list_files(ftp_path)
        sizes = [self.size(os.path.join(ftp_path, fn)) for fn in files]
        return zip(files, sizes)

    def download(self, ftp_path):
        localfn = os.path.join(config.download.datadir,os.path.basename(ftp_path))
        f = open(localfn, 'wb')
        
        # Define a function to write blocks to the file
        def write(block):
            f.write(block)
            f.flush()
            os.fsync(f)
        
        self.sendcmd("TYPE I")
        cout.outs("CornellFTP - Starting Download of: %s" % \
                        os.path.split(ftp_path)[-1])
        self.retrbinary("RETR "+ftp_path, write)
        f.close()
        cout.outs("CornellFTP - Finished download of: %s" % \
                        os.path.split(ftp_path)[-1])
        return localfn 

    def upload(self, local_path, ftp_path):
        f = open(local_path, 'r')
        
        self.sendcmd("TYPE I")
        cout.outs("CornellFTP - Starting upload of: %s" % \
                    os.path.split(local_path)[-1])
        try:
            self.storbinary("STOR "+ftp_path, f)
        except Exception, e:
            cout.outs("CornellFTP - Upload of %s failed: %s" % \
                        (os.path.split(local_path)[-1], str(e)))
            raise CornellFTPError("Could not store binary file (%s) " 
                                    "on FTP server: %s" % (ftp_path, str(e)))
        else:
            cout.outs("CornellFTP - Finished upload of: %s" % \
                        os.path.split(local_path)[-1])
        finally:
            f.close()
        
        # Check the size of the uploaded file
        ftp_size = self.size(ftp_path)
        local_size = os.path.getsize(local_path)
        if ftp_size == local_size:
            cout.outs("CornellFTP - Upload of %s successful." % \
                    os.path.split(local_path)[-1])
        else:
            cout.outs("CornellFTP - Upload of %s failed! " \
                        "File sizes of local file and " \
                        "uploaded file on FTP server " \
                        "don't match (%d != %d)." % \
                        (os.path.split(local_path)[-1], local_size, ftp_size))
            raise CornellFTPError("File sizes of local file and " \
                                    "uploaded file on FTP server " \
                                    "don't match (%d != %d)." % \
                                    (local_size, ftp_size))


class CornellFTPError(Exception):
    pass
