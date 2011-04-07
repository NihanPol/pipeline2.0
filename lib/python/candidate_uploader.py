#!/usr/bin/env python

"""
A candidate uploader for the PALFA survey.

Patrick Lazarus, Jan. 10th, 2011
"""
import os.path
import sys
import glob
import tarfile
import tempfile
import optparse
import traceback
import datetime
import shutil

import psr_utils
import prepfold
import upload
from formats import accelcands

# get configurations
import config.basic
import config.searching

class PeridocityCandidate(upload.Uploadable):
    """A class to represent a PALFA periodicity candidate.
    """
    def __init__(self, header_id, cand_num, pfd , snr, \
                        coherent_power, incoherent_power, \
                        num_hits, num_harmonics, versionnum, sigma):
        self.header_id = header_id # Header ID from database
        self.cand_num = cand_num # Unique identifier of candidate within beam's 
                                 # list of candidates; Candidate's position in
                                 # a list of all candidates produced in beam
                                 # ordered by decreasing sigma (where largest
                                 # sigma has cand_num=1).
        self.topo_freq, self.topo_f_dot, fdd = \
                psr_utils.p_to_f(pfd.topo_p1, pfd.topo_p2, pfd.topo_p3)
        self.bary_freq, self.bary_f_dot, baryfdd = \
                psr_utils.p_to_f(pfd.bary_p1, pfd.bary_p2, pfd.bary_p3)
        self.dm = pfd.bestdm # Dispersion measure
        self.snr = snr # signal-to-noise ratio
        self.coherent_power = coherent_power # Coherent power
        self.incoherent_power = incoherent_power # Incoherent power
        self.num_hits = num_hits # Number of dedispersed timeseries candidate was found in
        self.num_harmonics = num_harmonics # Number of harmonics candidate was 
                                           # most significant with
        self.versionnum = versionnum # Version number; a combination of PRESTO's githash
                                     # and pipeline's githash
        self.sigma = sigma # PRESTO's sigma value

        # Calculate a few more values
        self.topo_period = 1.0/self.topo_freq
        self.bary_period = 1.0/self.bary_freq

    def get_upload_sproc_call(self):
        """Return the EXEC spPDMCandUploaderFindsVersion string to upload
            this candidate to the PALFA common DB.
        """
        sprocstr = "EXEC spPDMCandUploaderFindsVersion " + \
            "@header_id=%d, " % self.header_id + \
            "@cand_num=%d, " % self.cand_num + \
            "@frequency=%.12g, " % self.topo_freq + \
            "@bary_frequency=%.12g, " % self.bary_freq + \
            "@period=%.12g, " % self.topo_period + \
            "@bary_period=%.12g, " % self.bary_period + \
            "@f_dot=%.12g, " % self.topo_f_dot + \
            "@bary_f_dot=%.12g, " % self.bary_f_dot + \
            "@dm=%.12g, " % self.dm + \
            "@snr=%.12g, " % self.snr + \
            "@coherent_power=%.12g, " % self.coherent_power + \
            "@incoherent_power=%.12g, " % self.incoherent_power + \
            "@num_hits=%d, " % self.num_hits + \
            "@num_harmonics=%d, " % self.num_harmonics + \
            "@institution='%s', " % config.basic.institution + \
            "@pipeline='%s', " % config.basic.pipeline + \
            "@version_number='%s', " % self.versionnum + \
            "@proc_date='%s', " % datetime.date.today().strftime("%Y-%m-%d") + \
            "@presto_sigma=%.12g" % self.sigma
        return sprocstr

    def __cmp__(self, other):
        return ('%d' % self.header_id == '%d' % other.header_id) and \
                ('%d' % self.cand_num == '%d' % other.cand_num) and \
                ('%.12g' % self.topo_freq == '%.12g' % other.topo_freq) and \
                ('%.12g' % self.bary_freq == '%.12g' % other.bary_freq) and \
                ('%.12g' % self.topo_period == '%.12g' % other.topo_period) and \
                ('%.12g' % self.bary_period == '%.12g' % other.bary_period) and \
                ('%.12g' % self.topo_f_dot == '%.12g' % other.topo_f_dot) and \
                ('%.12g' % self.bary_f_dot == '%.12g' % other.bary_f_dot) and \
                ('%.12g' % self.dm == '%.12g' % other.dm) and \
                ('%.12g' % self.snr == '%.12g' % other.snr) and \
                ('%.12g' % self.coherent_power == '%.12g' % other.coherent_power) and \
                ('%.12g' % self.incoherent_power == '%.12g' % other.incoherent_power) and \
                ('%d' % self.num_hits == '%d' % other.num_hits) and \
                ('%d' % self.num_harmonics == '%d' % other.num_harmonics) and \
                (lower(self.institution) == lower(other.institution)) and \
                (lower(self.pipeline) == lower(other.pipeline)) and \
                (lower(self.version_number) == lower(other.version_number)) and \
                (lower(self.institution) == lower(other.institution)) and \
                ('%.12g' % self.sigma == '%.12g' % other.sigma)

                
class PeriodicityCandidatePlot(upload.Uploadable):
    """A class to represent the plot of a PALFA periodicity candidate.
    """
    def __init__(self, cand_id, plotfn):
        self.cand_id = cand_id
        self.filename = os.path.split(plotfn)[-1]
        plot = open(plotfn, 'r')
        self.filedata = plot.read()
        plot.close()

    def get_upload_sproc_call(self):
        """Return the EXEC spPDMCandPlotUploader string to upload
            this candidate plot to the PALFA common DB.
        """
        sprocstr = "EXEC spPDMCandPlotLoader " + \
            "@pdm_cand_id=%d, " % self.cand_id + \
            "@pdm_plot_type='%s', " % self.plot_type + \
            "@filename='%s', " % os.path.split(self.filename)[-1] + \
            "@filedata=0x%s" % self.filedata.encode('hex')
        return sprocstr

    def __cmp__(self, other):
        return ('%d' % self.cand_id == '%d' % other.cand_id) and \
                ('%s' % self.plot_type == '%s' % other.plot_type) and \
                ('%s' % os.path.split(self.filename)[-1] == '%s' % os.path.split(other.filename)[-1]) and \
                ('0x%s' % self.filedata.encode('hex') == '0x%s' % other.filedata.encode('hex'))


class PeriodicityCandidatePNG(PeriodicityCandidatePlot):
    """A class to represent periodicity candidate PNGs.
    """
    plot_type = "prepfold plot"


class PeriodicityCandidatePFD(PeriodicityCandidatePlot):
    """A class to represent periodicity candidate PFD files.
    """
    plot_type = "pfd binary"


class PeriodicityCandidateError(Exception):
    """Error to throw when a candidate-specific problem is encountered.
    """
    pass


def upload_candidates(header_id, versionnum, directory, verbose=False, \
                        dry_run=False, *args, **kwargs):
    """Upload candidates to common DB.

        Inputs:
            header_id: header_id number for this beam, as returned by
                        spHeaderLoader/header.upload_header
            versionnum: A combination of the githash values from 
                        PRESTO and from the pipeline. 
            directory: The directory containing results from the pipeline.
            verbose: An optional boolean value that determines if information 
                        is printed to stdout.
            dry_run: An optional boolean value. If True no connection to DB
                        will be made and DB command will not be executed.
                        (If verbose is True DB command will be printed 
                        to stdout.)

            *** NOTE: Additional arguments are passed to the uploader function.

        Ouputs:
            cand_ids: List of candidate IDs corresponding to these candidates
                        in the common DB. (Or a list of None values if
                        dry_run is True).
    """
    # find *.accelcands file    
    candlists = glob.glob(os.path.join(directory, "*.accelcands"))
                                                
    if len(candlists) != 1:
        raise PeriodicityCandidateError("Wrong number of candidate lists found (%d)!" % \
                                            len(candlists))

    # Get list of candidates from *.accelcands file
    candlist = accelcands.parse_candlist(candlists[0])
    minsigma = config.searching.to_prepfold_sigma
    foldedcands = [c for c in candlist if c.sigma > minsigma]
    foldedcands = foldedcands[:config.searching.max_cands_to_fold]
    foldedcands.sort(reverse=True) # Sort by descending sigma
    
    # Create temporary directory
    tempdir = tempfile.mkdtemp(suffix="_tmp", prefix="PALFA_pfds_")
    tarfns = glob.glob(os.path.join(directory, "*_pfd.tgz"))
    if len(tarfns) != 1:
        raise PeriodicityCandidateError("Wrong number (%d) of *_pfd.tgz " \
                                         "files found in %s" % (len(tarfns), \
                                            directory))
    tar = tarfile.open(tarfns[0])
    tar.extractall(path=tempdir)
    tar.close()
    # Loop over candidates that were folded
    results = []
    for ii, c in enumerate(foldedcands):
        basefn = "%s_ACCEL_Cand_%d" % (c.accelfile.replace("ACCEL_", "Z"), \
                                    c.candnum)
        pfdfn = os.path.join(tempdir, basefn+".pfd")
        pngfn = os.path.join(directory, basefn+".pfd.png")
        
        pfd = prepfold.pfd(pfdfn)
        
        try:
            cand = PeridocityCandidate(header_id, ii+1, pfd, c.snr, \
                                    c.cpow, c.ipow, len(c.dmhits), \
                                    c.numharm, versionnum, c.sigma)
        except Exception:
            raise PeriodicityCandidateError("PeriodicityCandidate could not be " \
                                            "created (%s)!" % pfdfn)

        if dry_run:
            cand.get_upload_sproc_call()
            if verbose:
                print cand
            results.append(None)
            cand_id = -1
        else:
            cand_id = cand.upload(*args, **kwargs)
        
        pfdplot = PeriodicityCandidatePFD(cand_id, pfdfn)
        pngplot = PeriodicityCandidatePNG(cand_id, pngfn)
        if dry_run:
            pfdplot.get_upload_sproc_call()
            pngplot.get_upload_sproc_call()
            if verbose:
                print pfdplot
                print pngplot
        else:
            pfdplot.upload(*args, **kwargs)
            pngplot.upload(*args, **kwargs)
        
    shutil.rmtree(tempdir)
    return results

def main():
    try:
        upload_candidates(options.header_id, options.versionnum, \
                            options.directory, options.verbose, \
                            options.dry_run)
    except upload.UploadError, e:
        traceback.print_exception(*sys.exc_info())
        sys.stderr.write("\nOriginal exception thrown:\n")
        traceback.print_exception(*e.orig_exc)

if __name__ == '__main__':
    parser = optparse.OptionParser(prog="candidate_uploader.py", \
                version="v0.8 (by Patrick Lazarus, Jan. 12, 2011)", \
                description="Upload candidates from a beam of PALFA " \
                            "data analysed using the pipeline2.0.")
    parser.add_option('--header-id', dest='header_id', type='int', \
                        help="Header ID of this beam from the common DB.")
    parser.add_option('--versionnum', dest='versionnum', \
                        help="Version number is a combination of the PRESTO " \
                             "repository's git hash and the Pipeline2.0 " \
                             "repository's git has in the following format " \
                             "PRESTO:prestohash;pipeline:prestohash")
    parser.add_option('-d', '--directory', dest='directory',
                        help="Directory containing results from processing. " \
                             "Diagnostic information will be derived from the " \
                             "contents of this directory.")
    parser.add_option('--verbose', dest='verbose', action='store_true', \
                        help="Print success/failure information to screen. " \
                             "(Default: do not print).", \
                        default=False)
    parser.add_option('-n', '--dry-run', dest='dry_run', action='store_true', \
                        help="Perform a dry run. Do everything but connect to " \
                             "DB and upload candidate info. If --verbose " \
                             "is set, DB commands will be displayed on stdout. " \
                             "(Default: Connect to DB and execute commands).", \
                        default=False)
    options, args = parser.parse_args()
    main()
 

