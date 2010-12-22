import glob
import os
import os.path
import shutil
import socket
import struct
import sys
import time
import subprocess
import warnings
import re
import types
import tarfile

import numpy as np
import psr_utils
import presto
import sifting
import DDplan2b
from formats import psrfits

# Basic parameters
# institution is one of: 'UBC', 'NRAOCV', 'McGill', 'Columbia', 'Cornell', 'UTB'
# institution           = "NRAOCV" 
# base_output_directory = "/home/fcardoso/results/PALFA"
# db_pointing_file      = "/home/fcardoso/results/PALFA/PALFA_coords_table.txt"

# The following determines if we'll dedisperse and fold using subbands.
# In general, it is a very good idea to use them if there is enough scratch
# space on the machines that are processing (~30GB/beam processed)
use_subbands          = True

# To fold from raw data (ie not from subbands or dedispersed FITS files)
# set the following to True.
fold_rawdata          = True

# Tunable parameters for searching and folding
# (you probably don't need to tune any of them)
datatype_flag           = "-psrfits" # PRESTO flag to determine data type
rfifind_chunk_time      = 2**15 * 0.000064  # ~2.1 sec for dt = 64us
singlepulse_threshold   = 5.0  # threshold SNR for candidate determination
singlepulse_plot_SNR    = 6.0  # threshold SNR for singlepulse plot
singlepulse_maxwidth    = 0.1  # max pulse width in seconds
to_prepfold_sigma       = 6.0  # incoherent sum significance to fold candidates
max_cands_to_fold       = 150   # Never fold more than this many candidates
numhits_to_fold         = 2    # Number of DMs with a detection needed to fold
low_DM_cutoff           = 2.0  # Lowest DM to consider as a "real" pulsar
lo_accel_numharm        = 16   # max harmonics
lo_accel_sigma          = 2.0  # threshold gaussian significance
lo_accel_zmax           = 0    # bins
lo_accel_flo            = 2.0  # Hz
hi_accel_numharm        = 8    # max harmonics
hi_accel_sigma          = 3.0  # threshold gaussian significance
hi_accel_zmax           = 50   # bins
hi_accel_flo            = 1.0  # Hz
low_T_to_search         = 20.0 # sec

# DDplan configurations
lodm = 0            # pc cm-3
hidm = 1000         # pc cm-3
resolution = 0.1    # ms
if use_subbands:
    numsub = 32     # subbands
else:
    numsub = 0      # Defaults to number of channels

# Sifting specific parameters (don't touch without good reason!)
sifting.sigma_threshold = to_prepfold_sigma-1.0  # incoherent power threshold (sigma)
sifting.c_pow_threshold = 100.0                  # coherent power threshold
sifting.r_err           = 1.1    # Fourier bin tolerence for candidate equivalence
sifting.short_period    = 0.0005 # Shortest period candidates to consider (s)
sifting.long_period     = 15.0   # Longest period candidates to consider (s)
sifting.harm_pow_cutoff = 8.0    # Power required in at least one harmonic

debug = 0


def get_baryv(ra, dec, mjd, T, obs="AO"):
   """
   get_baryv(ra, dec, mjd, T):
     Determine the average barycentric velocity towards 'ra', 'dec'
       during an observation from 'obs'.  The RA and DEC are in the
       standard string format (i.e. 'hh:mm:ss.ssss' and 
       'dd:mm:ss.ssss'). 'T' is in sec and 'mjd' is (of course) in MJD.
   """
   tts = psr_utils.span(mjd, mjd+T/86400.0, 100)
   nn = len(tts)
   bts = np.zeros(nn, dtype=np.float64)
   vel = np.zeros(nn, dtype=np.float64)
   presto.barycenter(tts, bts, vel, nn, ra, dec, obs, "DE200")
   avgvel = np.add.reduce(vel)/nn
   return avgvel

def find_masked_fraction(obs):
    """
    find_masked_fraction(obs):
        Parse the output file from an rfifind run and return the
            fraction of the data that was suggested to be masked.
    """
    rfifind_out = obs.basefilenm + "_rfifind.out"
    for line in open(rfifind_out):
        if "Number of  bad   intervals" in line:
            return float(line.split("(")[1].split("%")[0])/100.0
    # If there is a problem reading the file, return 100%
    return 100.0

def get_all_subdms(ddplans):
    """
    get_all_subdms(ddplans):
        Return a sorted array of the subdms from the list of ddplans.
    """
    subdmlist = []
    for ddplan in ddplans:
        subdmlist += [float(x) for x in ddplan.subdmlist]
    subdmlist.sort()
    subdmlist = np.asarray(subdmlist)
    return subdmlist


def find_closest_subbands(obs, subdms, DM):
    """
    find_closest_subbands(obs, subdms, DM):
        Return the basename of the closest set of subbands to DM
        given an obs_info class and a sorted array of the subdms.
    """
    subdm = subdms[np.fabs(subdms - DM).argmin()]
    return "subbands/%s_DM%.2f.sub[0-6]*"%(obs.basefilenm, subdm)


def timed_execute(cmd, stdout=None, stderr=sys.stderr): 
    """
    timed_execute(cmd, stdout=None, stderr=sys.stderr):
        Execute the command 'cmd' after logging the command
            to STDOUT.  Return the wall-clock amount of time
            the command took to execute.

            Output standard output to 'stdout' and standard
            error to 'stderr'. Both are strings containing filenames.
            If values are None, the out/err streams are not recorded.
            By default stdout is None and stderr is combined with stdout.
    """
    # Log command to stdout
    sys.stdout.write("\n'"+cmd+"'\n")
    sys.stdout.flush()

    stdoutfile = False
    stderrfile = False
    if type(stdout) == types.StringType:
        stdout = open(stdout, 'w')
        stdoutfile = True
    if type(stderr) == types.StringType:
        stderr = open(stderr, 'w')
        stderrfile = True
    
    # Run (and time) the command. Check for errors.
    start = time.time()
    retcode = subprocess.call(cmd, shell=True, stdout=stdout, stderr=stderr)
    if retcode < 0:
        raise PrestoError("Execution of command (%s) terminated by signal (%s)!" % \
                                (cmd, -retcode))
    elif retcode > 0:
        raise PrestoError("Execution of command (%s) failed with status (%s)!" % \
                                (cmd, retcode))
    else:
        # Exit code is 0, which is "Success". Do nothing.
        pass
    end = time.time()
    
    # Close file objects, if any
    if stdoutfile:
        stdout.close()
    if stderrfile:
        stderr.close()
    return end - start


def get_folding_command(cand, obs, ddplans):
    """
    get_folding_command(cand, obs, ddplans):
        Return a command for prepfold for folding the subbands using
            an obs_info instance, a list of the ddplans, and a candidate 
            instance that describes the observations and searches.
    """
    # Folding rules are based on the facts that we want:
    #   1.  Between 24 and 200 bins in the profiles
    #   2.  For most candidates, we want to search length = 101 p/pd/DM cubes
    #       (The side of the cube is always 2*M*N+1 where M is the "factor",
    #       either -npfact (for p and pd) or -ndmfact, and N is the number of bins
    #       in the profile).  A search of 101^3 points is pretty fast.
    #   3.  For slow pulsars (where N=100 or 200), since we'll have to search
    #       many points, we'll use fewer intervals in time (-npart 30)
    #   4.  For the slowest pulsars, in order to avoid RFI, we'll
    #       not search in period-derivative.
    zmax = cand.filename.split("_")[-1]
    outfilenm = obs.basefilenm+"_DM%s_Z%s"%(cand.DMstr, zmax)

    # Note:  the following calculations should probably only be done once,
    #        but in general, these calculation are effectively instantaneous
    #        compared to the folding itself
    if fold_rawdata:
        # Fold raw data
        foldfiles = obs.filenmstr
    else:
        if use_subbands:
            # Fold the subbands
            subdms = get_all_subdms(ddplans)
            subfiles = find_closest_subbands(obs, subdms, cand.DM)
            foldfiles = subfiles
        else:  # Folding the downsampled PSRFITS files instead
            hidms = [x.lodm for x in ddplans[1:]] + [2000]
            dfacts = [x.downsamp for x in ddplans]
            for hidm, dfact in zip(hidms, dfacts):
                if cand.DM < hidm:
                    downsamp = dfact
                    break
            if downsamp==1:
                foldfiles = obs.filenmstr
            else:
                dsfiles = [] 
                for f in obs.filenames:
                    fbase = f.rstrip(".fits")
                    dsfiles.append(fbase+"_DS%d.fits"%downsamp)
                foldfiles = ' '.join(dsfiles)
    p = 1.0 / cand.f
    if p < 0.002:
        Mp, Mdm, N = 2, 2, 24
        otheropts = "-npart 50 -ndmfact 3"
    elif p < 0.05:
        Mp, Mdm, N = 2, 1, 50
        otheropts = "-npart 40 -pstep 1 -pdstep 2 -dmstep 3"
    elif p < 0.5:
        Mp, Mdm, N = 1, 1, 100
        otheropts = "-npart 30 -pstep 1 -pdstep 2 -dmstep 1"
    else:
        Mp, Mdm, N = 1, 1, 200
        otheropts = "-npart 30 -nopdsearch -pstep 1 -pdstep 2 -dmstep 1"
    return "prepfold -noxwin -accelcand %d -accelfile %s.cand -dm %.2f -o %s %s -n %d -npfact %d -ndmfact %d %s" % \
           (cand.candnum, cand.filename, cand.DM, outfilenm,
            otheropts, N, Mp, Mdm, foldfiles)


class obs_info:
    """
    class obs_info(filenms, resultsdir)
        A class describing the observation and the analysis.
    """
    def __init__(self, filenms, resultsdir):
        # Where to dump all the results
        self.outputdir = resultsdir
        
        self.filenms = filenms
        self.filenmstr = ' '.join(self.filenms)
        self.basefilenm = os.path.split(filenms[0])[1].rstrip(".fits")
        
        # Read info from PSRFITS file
        spec_info = psrfits.SpectraInfo(filenms)
        self.backend = spec_info.backend
        self.MJD = spec_info.start_MJD[0]
        self.ra_string = spec_info.ra_str
        self.dec_string = spec_info.dec_str
        self.orig_N = spec_info.N
        self.dt = spec_info.dt # in sec
        self.BW = spec_info.BW
        self.orig_T = spec_info.T
        # Downsampling is catered to the number of samples per row.
        # self.N = psr_utils.choose_N(self.orig_N)
        self.N = self.orig_N
        self.T = self.N * self.dt
        self.nchan = spec_info.num_channels
        self.samp_per_row = spec_info.spectra_per_subint
        self.fctr = spec_info.fctr
        #
        ###################################################
        # Should we worry about correcting faulty positions
        # in the file header?
        # Say, for wapp2psrfits files?
        # -PL
        ###################################################
        #
        # Determine the average barycentric velocity of the observation
        self.baryv = get_baryv(self.ra_string, self.dec_string,
                               self.MJD, self.T, obs="AO")
        # Figure out which host we are processing on
        self.hostname = socket.gethostname()
        # The fraction of the data recommended to be masked by rfifind
        self.masked_fraction = 0.0
        # Initialize our timers
        self.rfifind_time = 0.0
        self.downsample_time = 0.0
        self.subbanding_time = 0.0
        self.dedispersing_time = 0.0
        self.FFT_time = 0.0
        self.lo_accelsearch_time = 0.0
        self.hi_accelsearch_time = 0.0
        self.singlepulse_time = 0.0
        self.sifting_time = 0.0
        self.folding_time = 0.0
        self.total_time = 0.0
        # Inialize some candidate counters
        self.num_sifted_cands = 0
        self.num_folded_cands = 0
        self.num_single_cands = 0

    def write_report(self, filenm):
        report_file = open(filenm, "w")
        report_file.write("---------------------------------------------------------\n")
        report_file.write("Data (%s) were processed on %s\n" % \
                                (', '.join(self.filenms), self.hostname))
        report_file.write("Ending UTC time:  %s\n"%(time.asctime(time.gmtime())))
        report_file.write("Total wall time:  %.1f s (%.2f hrs)\n"%\
                          (self.total_time, self.total_time/3600.0))
        report_file.write("Fraction of data masked:  %.2f%%\n"%\
                          (self.masked_fraction*100.0))
        report_file.write("---------------------------------------------------------\n")
        report_file.write("          rfifind time = %7.1f sec (%5.2f%%)\n"%\
                          (self.rfifind_time, self.rfifind_time/self.total_time*100.0))
        if use_subbands:
            report_file.write("       subbanding time = %7.1f sec (%5.2f%%)\n"%\
                              (self.subbanding_time, self.subbanding_time/self.total_time*100.0))
        else:
            report_file.write("     downsampling time = %7.1f sec (%5.2f%%)\n"%\
                              (self.downsample_time, self.downsample_time/self.total_time*100.0))
        report_file.write("     dedispersing time = %7.1f sec (%5.2f%%)\n"%\
                          (self.dedispersing_time, self.dedispersing_time/self.total_time*100.0))
        report_file.write("     single-pulse time = %7.1f sec (%5.2f%%)\n"%\
                          (self.singlepulse_time, self.singlepulse_time/self.total_time*100.0))
        report_file.write("              FFT time = %7.1f sec (%5.2f%%)\n"%\
                          (self.FFT_time, self.FFT_time/self.total_time*100.0))
        report_file.write("   lo-accelsearch time = %7.1f sec (%5.2f%%)\n"%\
                          (self.lo_accelsearch_time, self.lo_accelsearch_time/self.total_time*100.0))
        report_file.write("   hi-accelsearch time = %7.1f sec (%5.2f%%)\n"%\
                          (self.hi_accelsearch_time, self.hi_accelsearch_time/self.total_time*100.0))
        report_file.write("          sifting time = %7.1f sec (%5.2f%%)\n"%\
                          (self.sifting_time, self.sifting_time/self.total_time*100.0))
        report_file.write("          folding time = %7.1f sec (%5.2f%%)\n"%\
                          (self.folding_time, self.folding_time/self.total_time*100.0))
        report_file.write("---------------------------------------------------------\n")
        report_file.close()

class dedisp_plan:
    """
    class dedisp_plan(lodm, dmstep, dmsperpass, numpasses, numsub, downsamp)
        A class describing a de-dispersion plan for prepsubband in detail.
    """
    def __init__(self, lodm, dmstep, dmsperpass, numpasses, numsub, downsamp):
        self.lodm = float(lodm)
        self.dmstep = float(dmstep)
        self.dmsperpass = int(dmsperpass)
        self.numpasses = int(numpasses)
        self.numsub = int(numsub)
        self.downsamp = int(downsamp)
        # Downsample less for the subbands so that folding
        # candidates is more acurate
        #
        # Turning this off because downsampling factors are not necessarily
        # powers of 2 any more! Also, are we folding from raw data now?
        # -- PL Nov. 26, 2010
        #
        self.sub_downsamp = self.downsamp
        self.dd_downsamp = 1
        # self.sub_downsamp = self.downsamp / 2
        # if self.sub_downsamp==0: self.sub_downsamp = 1
        # The total downsampling is:
        #   self.downsamp = self.sub_downsamp * self.dd_downsamp

        # if self.downsamp==1: self.dd_downsamp = 1
        # else: self.dd_downsamp = 2
        self.sub_dmstep = self.dmsperpass * self.dmstep
        self.dmlist = []  # These are strings for comparison with filenames
        self.subdmlist = []
        for ii in range(self.numpasses):
            self.subdmlist.append("%.2f"%(self.lodm + (ii+0.5)*self.sub_dmstep))
            lodm = self.lodm + ii * self.sub_dmstep
            dmlist = ["%.2f"%dm for dm in \
                      np.arange(self.dmsperpass)*self.dmstep + lodm]
            self.dmlist.append(dmlist)

#ddplans = []
#if (1):
#    #
#    # Using a small DDplan for debugging
#    # Generated using:
#    #   DDplan.py -l 0 -d 400 -f 1450.168 -b 172.0625 
#    #               -n 256 -t 6.5476190476190506e-05 -r 2 -s 32
#    # I set downsamp equal to 1, though.
#    # -PL
#    #
#    # The values here are:       lodm dmstep dms/call #calls #subbands downsamp
#    ddplans.append(dedisp_plan(   0.0,   3,      24,     6,       32,       1))


def set_DDplan(job, backend):
    """Set the dedispersion plan as a global variable.

        The dedispersion plans are hardcoded and 
        depend on the backend data were recorded with.
    """
    # Generate dedispersion plan
    global ddplans
    ddplans = []
    
    # The following code will run the dedispersion planner on demand.
    # Instead, dedispersion plans for WAPP and Mock data are hardcoded.
    #
    # obs = DDplan2b.Observation(job.dt, job.fctr, job.BW, job.nchan, \
    #                             job.samp_per_row)
    # plan = obs.gen_ddplan(lodm, hidm, numsub, resolution)
    # plan.plot(fn=os.path.join(job.outputdir, job.basefilenm+"_ddplan.ps"))
    # print plan
    # for ddstep in plan.DDsteps:
    #     ddplans.append(dedisp_plan(ddstep.loDM, ddstep.dDM, ddstep.DMs_per_prepsub, \
    #                    ddstep.numprepsub, ddstep.numsub, ddstep.downsamp))
    
    if backend.lower() == 'pdev':
        # The values here are:       lodm dmstep dms/call #calls #subbands downsamp
        ddplans.append(dedisp_plan(   0.0,  0.1,    76,     28,     96,        1 ))
        ddplans.append(dedisp_plan( 212.8,  0.3,    64,     12,     96,        2 ))
        ddplans.append(dedisp_plan( 443.2,  0.3,    76,      4,     96,        3 ))
        ddplans.append(dedisp_plan( 534.4,  0.5,    76,      9,     96,        5 ))
        ddplans.append(dedisp_plan( 876.4,  0.5,    76,      3,     96,        6 ))
        ddplans.append(dedisp_plan( 990.4,  1.0,    76,      1,     96,       10 ))
    elif backend.lower() == 'wapp':
        # The values here are:       lodm dmstep dms/call #calls #subbands downsamp
        ddplans.append(dedisp_plan(   0.0,  0.3,    76,      9,     96,        1 ))
        ddplans.append(dedisp_plan( 205.2,  2.0,    76,      5,     96,        5 ))
        ddplans.append(dedisp_plan( 965.2, 10.0,    76,      1,     96,       25 ))
    else:
        raise ValueError("No dediserpsion plan for unknown backend (%s)!" % backend)


def main(filenms, workdir, resultsdir):

    # Change to the specified working directory
    os.chdir(workdir)

    job = set_up_job(filenms, workdir, resultsdir)
    
    print "\nBeginning PALFA search of %s" % (', '.join(job.filenms))
    print "UTC time is:  %s"%(time.asctime(time.gmtime()))
    
    try:
        search_job(job)
    except:
        print "Search has been aborted due to errors encountered."
        print "See error output for more information."
        sys.excepthook(*sys.exc_info())
    finally:
        clean_up(job)

        # And finish up
        job.total_time = time.time() - job.total_time
        print "\nFinished"
        print "UTC time is:  %s"%(time.asctime(time.gmtime()))

        # Write the job report
        # job.write_report(job.basefilenm+".report")
        job.write_report(os.path.join(job.outputdir, job.basefilenm+".report"))

    
def set_up_job(filenms, workdir, resultsdir):
    """Change to the working directory and set it up.
        Create a obs_info instance, set it up and return it.
    """
    # Get information on the observation and the job
    job = obs_info(filenms, resultsdir)
    if job.T < low_T_to_search:
        sys.exit("The observation is too short (%.2f s) to search."%job.T)
    job.total_time = time.time()
    
    # Make sure the output directory (and parent directories) exist
    try:
        os.makedirs(job.outputdir)
    except: pass

    # Create a directory to hold all the subbands
    if use_subbands:
        try:
            os.makedirs("subbands")
        except: pass
    
    return job


def search_job(job):
    """Search the observation defined in the obs_info
        instance 'job'.
    """
    set_DDplan(job, job.backend)

    # Use whatever .zaplist is found in the current directory
    default_zaplist = glob.glob("*.zaplist")[0]

    # rfifind the data file
    cmd = "rfifind %s -time %.17g -o %s %s" % \
          (datatype_flag, rfifind_chunk_time, job.basefilenm,
           job.filenmstr)
    job.rfifind_time += timed_execute(cmd, stdout="%s_rfifind.out" % job.basefilenm)
    maskfilenm = job.basefilenm + "_rfifind.mask"
    # Find the fraction that was suggested to be masked
    # Note:  Should we stop processing if the fraction is
    #        above some large value?  Maybe 30%?
    job.masked_fraction = find_masked_fraction(job)
    
    # Iterate over the stages of the overall de-dispersion plan
    dmstrs = []
    for ddplan in ddplans:

        # Make a downsampled filterbank file if we are not using subbands
        if not use_subbands:
            if ddplan.downsamp > 1:
                cmd = "downsample_psrfits.py %d %s"%(ddplan.downsamp, job.filenmstr)
                job.downsample_time += timed_execute(cmd)
                dsfiles = []
                for f in job.filenames:
                    fbase = f.rstrip(".fits")
                    dsfiles.append(fbase+"_DS%d.fits"%ddplan.downsamp)
                filenmstr = ' '.join(dsfiles)
            else:
                filenmstr = job.filenmstr 

        # Iterate over the individual passes through the data file
        for passnum in range(ddplan.numpasses):
            subbasenm = "%s_DM%s"%(job.basefilenm, ddplan.subdmlist[passnum])

            if use_subbands:
                # Create a set of subbands
                cmd = "prepsubband %s -sub -subdm %s -downsamp %d -nsub %d -mask %s " \
                        "-o subbands/%s %s" % \
                        (datatype_flag, ddplan.subdmlist[passnum], ddplan.sub_downsamp,
                        ddplan.numsub, maskfilenm, job.basefilenm,
                        job.filenmstr)
                job.subbanding_time += timed_execute(cmd, stdout="%s.subout" % subbasenm)
            
                # Now de-disperse using the subbands
                cmd = "prepsubband -lodm %.2f -dmstep %.2f -numdms %d -downsamp %d " \
                        "-numout %d -o %s subbands/%s.sub[0-9]*" % \
                        (ddplan.lodm+passnum*ddplan.sub_dmstep, ddplan.dmstep,
                        ddplan.dmsperpass, ddplan.dd_downsamp, 
                        psr_utils.choose_N(job.orig_N/ddplan.downsamp),
                        job.basefilenm, subbasenm)
                job.dedispersing_time += timed_execute(cmd, stdout="%s.prepout" % subbasenm)
            
            else:  # Not using subbands
                cmd = "prepsubband -mask %s -lodm %.2f -dmstep %.2f -numdms %d " \
                        "-numout %d -o %s %s"%\
                        (maskfilenm, ddplan.lodm+passnum*ddplan.sub_dmstep, ddplan.dmstep,
                        ddplan.dmsperpass, psr_utils.choose_N(job.orig_N/ddplan.downsamp),
                        job.basefilenm, filenmstr)
                job.dedispersing_time += timed_execute(cmd)
            
            # Iterate over all the new DMs
            for dmstr in ddplan.dmlist[passnum]:
                dmstrs.append(dmstr)
                basenm = job.basefilenm+"_DM"+dmstr
                datnm = basenm+".dat"
                fftnm = basenm+".fft"
                infnm = basenm+".inf"

                # Do the single-pulse search
                cmd = "single_pulse_search.py -p -m %f -t %f %s"%\
                      (singlepulse_maxwidth, singlepulse_threshold, datnm)
                job.singlepulse_time += timed_execute(cmd)

                # FFT, zap, and de-redden
                cmd = "realfft %s"%datnm
                job.FFT_time += timed_execute(cmd)
                cmd = "zapbirds -zap -zapfile %s -baryv %.6g %s"%\
                      (default_zaplist, job.baryv, fftnm)
                job.FFT_time += timed_execute(cmd)
                cmd = "rednoise %s"%fftnm
                job.FFT_time += timed_execute(cmd)
                try:
                    os.rename(basenm+"_red.fft", fftnm)
                except: pass
                
                # Do the low-acceleration search
                cmd = "accelsearch -harmpolish -numharm %d -sigma %f " \
                        "-zmax %d -flo %f %s"%\
                        (lo_accel_numharm, lo_accel_sigma, lo_accel_zmax, \
                        lo_accel_flo, fftnm)
                job.lo_accelsearch_time += timed_execute(cmd)
                try:
                    os.remove(basenm+"_ACCEL_%d.txtcand"%lo_accel_zmax)
                except: pass
        
                # Do the high-acceleration search
                cmd = "accelsearch -harmpolish -numharm %d -sigma %f " \
                        "-zmax %d -flo %f %s"%\
                        (hi_accel_numharm, hi_accel_sigma, hi_accel_zmax, \
                        hi_accel_flo, fftnm)
                job.hi_accelsearch_time += timed_execute(cmd)
                try:
                    os.remove(basenm+"_ACCEL_%d.txtcand"%hi_accel_zmax)
                except: pass

                # Remove the .dat and .fft files
                try:
                    os.remove(datnm)
                    os.remove(fftnm)
                except: pass

    # Make the single-pulse plots
    basedmb = job.basefilenm+"_DM"
    basedme = ".singlepulse "
    # The following will make plots for DM ranges:
    #    0-110, 100-310, 300-1000+
    dmglobs = [basedmb+"[0-9].[0-9][0-9]"+basedme +
               basedmb+"[0-9][0-9].[0-9][0-9]"+basedme +
               basedmb+"10[0-9].[0-9][0-9]"+basedme,
               basedmb+"[12][0-9][0-9].[0-9][0-9]"+basedme +
               basedmb+"30[0-9].[0-9][0-9]"+basedme,
               basedmb+"[3-9][0-9][0-9].[0-9][0-9]"+basedme +
               basedmb+"1[0-9][0-9][0-9].[0-9][0-9]"+basedme]
    dmrangestrs = ["0-110", "100-310", "300-1000+"]
    psname = job.basefilenm+"_singlepulse.ps"
    for dmglob, dmrangestr in zip(dmglobs, dmrangestrs):
        dmfiles = []
        for dmg in dmglob.split():
            dmfiles += glob.glob(dmg.strip())
        # Check that there are matching files and they are not all empty
        if dmfiles and sum([os.path.getsize(f) for f in dmfiles]):
            cmd = 'single_pulse_search.py -t %f -g "%s"' % \
                (singlepulse_plot_SNR, dmglob)
            job.singlepulse_time += timed_execute(cmd)
            os.rename(psname,
                        job.basefilenm+"_DMs%s_singlepulse.ps"%dmrangestr)

    # Sift through the candidates to choose the best to fold
    job.sifting_time = time.time()

    lo_accel_cands = sifting.read_candidates(glob.glob("*ACCEL_%d"%lo_accel_zmax))
    if len(lo_accel_cands):
        lo_accel_cands = sifting.remove_duplicate_candidates(lo_accel_cands)
    if len(lo_accel_cands):
        lo_accel_cands = sifting.remove_DM_problems(lo_accel_cands, numhits_to_fold,
                                                    dmstrs, low_DM_cutoff)

    hi_accel_cands = sifting.read_candidates(glob.glob("*ACCEL_%d"%hi_accel_zmax))
    if len(hi_accel_cands):
        hi_accel_cands = sifting.remove_duplicate_candidates(hi_accel_cands)
    if len(hi_accel_cands):
        hi_accel_cands = sifting.remove_DM_problems(hi_accel_cands, numhits_to_fold,
                                                    dmstrs, low_DM_cutoff)

    all_accel_cands = lo_accel_cands + hi_accel_cands
    if len(all_accel_cands):
        all_accel_cands = sifting.remove_harmonics(all_accel_cands)
        # Note:  the candidates will be sorted in _sigma_ order, not _SNR_!
        all_accel_cands.sort(sifting.cmp_sigma)
        sifting.write_candlist(all_accel_cands, job.basefilenm+".accelcands")

    try:
        cmd = "cp *.accelcands "+job.outputdir
        timed_execute(cmd)
    except: pass

    job.sifting_time = time.time() - job.sifting_time

    # Fold the best candidates

    cands_folded = 0
    for cand in all_accel_cands:
        if cands_folded == max_cands_to_fold:
            break
        if cand.sigma > to_prepfold_sigma:
            job.folding_time += timed_execute(get_folding_command(cand, job, ddplans))
            cands_folded += 1

    # Now step through the .ps files and convert them to .png and gzip them

    psfiles = glob.glob("*.ps")
    for psfile in psfiles:
        if "singlepulse" in psfile:
            # For some reason the singlepulse files don't transform nicely...
            # epsfile = psfile.replace(".ps", ".eps")
            # timed_execute("eps2eps "+psfile+" "+epsfile)
            # timed_execute("pstoimg -quiet -density 100 -crop a "+epsfile)
            timed_execute("convert -quality 90 %s -background white -flatten -rotate 90 +matte %s" % (psfile, psfile[:-3]+".png"))
            # try:
            #     os.remove(epsfile)
            # except: pass
        else:
            # timed_execute("pstoimg -quiet -density 100 -flip cw "+psfile)
            timed_execute("convert -quality 90 %s -background white -flatten -rotate 90 +matte %s" % (psfile, psfile[:-3]+".png"))
        timed_execute("gzip "+psfile)
    

def clean_up(job):
    """Clean up.
        Tar results, copy them to the results director.
    """
    # NOTE:  need to add database commands

    # Tar up the results files 
    tar_suffixes = ["_ACCEL_%d.tgz"%lo_accel_zmax,
                    "_ACCEL_%d.tgz"%hi_accel_zmax,
                    "_ACCEL_%d.cand.tgz"%lo_accel_zmax,
                    "_ACCEL_%d.cand.tgz"%hi_accel_zmax,
                    "_singlepulse.tgz",
                    "_inf.tgz",
                    "_pfd.tgz",
                    "_bestprof.tgz"]
    tar_globs = ["*_ACCEL_%d"%lo_accel_zmax,
                 "*_ACCEL_%d"%hi_accel_zmax,
                 "*_ACCEL_%d.cand"%lo_accel_zmax,
                 "*_ACCEL_%d.cand"%hi_accel_zmax,
                 "*.singlepulse",
                 "*_DM[0-9]*.inf",
                 "*.pfd",
                 "*.pfd.bestprof"]
    for (tar_suffix, tar_glob) in zip(tar_suffixes, tar_globs):
        tf = tarfile.open(job.basefilenm+tar_suffix, "w:gz")
        for infile in glob.glob(tar_glob):
            tf.add(infile)
            os.remove(infile)
    tf.close()
    
    # Copy all the important stuff to the output directory
    resultglobs = ["*rfifind.[bimors]*", 
                    "*.ps.gz", "*.tgz", "*.png"]
    for resultglob in resultglobs:
            for file in glob.glob(resultglob):
                shutil.copy(file, job.outputdir)
   

class PrestoError(Exception):
    """Error to throw when a PRESTO program returns with 
        a non-zero error code.
    """
    pass


if __name__ == "__main__":
    # Arguments to the search program are
    # sys.argv[3:] = data file names
    # sys.argv[1] = working directory name
    # sys.argv[2] = results directory name
    workdir = sys.argv[1]
    resultsdir = sys.argv[2]
    filenms = sys.argv[3:]
    main(filenms, workdir, resultsdir)
