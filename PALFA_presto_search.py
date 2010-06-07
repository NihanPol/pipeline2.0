import glob, os, os.path, shutil, socket, struct
import numpy, sys, psr_utils, presto, time
import sifting

# get configurations from config file
from PALFA_config import *

# Sifting specific parameters (don't touch without good reason!)
sifting.sigma_threshold = to_prepfold_sigma-1.0  # incoherent power threshold (sigma)
sifting.c_pow_threshold = 100.0                  # coherent power threshold
sifting.r_err           = 1.1    # Fourier bin tolerence for candidate equivalence
sifting.short_period    = 0.0005 # Shortest period candidates to consider (s)
sifting.long_period     = 15.0   # Longest period candidates to consider (s)
sifting.harm_pow_cutoff = 8.0    # Power required in at least one harmonic
			

debug = 0

# A list of numbers that are highly factorable
#goodfactors = [int(x) for x in open("ALFA_goodfacts.txt")]
goodfactors = [1008, 1024, 1056, 1120, 1152, 1200, 1232, 1280, 1296,
1344, 1408, 1440, 1536, 1568, 1584, 1600, 1680, 1728, 1760, 1792,
1920, 1936, 2000, 2016, 2048, 2112, 2160, 2240, 2304, 2352, 2400,
2464, 2560, 2592, 2640, 2688, 2800, 2816, 2880, 3024, 3072, 3136,
3168, 3200, 3360, 3456, 3520, 3584, 3600, 3696, 3840, 3872, 3888,
3920, 4000, 4032, 4096, 4224, 4320, 4400, 4480, 4608, 4704, 4752,
4800, 4928, 5040, 5120, 5184, 5280, 5376, 5488, 5600, 5632, 5760,
5808, 6000, 6048, 6144, 6160, 6272, 6336, 6400, 6480, 6720, 6912,
7040, 7056, 7168, 7200, 7392, 7680, 7744, 7776, 7840, 7920, 8000,
8064, 8192, 8400, 8448, 8624, 8640, 8800, 8960, 9072, 9216, 9408,
9504, 9600, 9680, 9856]

def choose_N(orig_N):
    """
    choose_N(orig_N):
        Choose a time series length that is larger than
            the input value but that is highly factorable.
            Note that the returned value must be divisible
            by at least the maximum downsample factor * 2.
            Currently, this is 8 * 2 = 16.
    """
    if orig_N < 10000:
        return 0
    # Get the number represented by the first 4 digits of orig_N
    first4 = int(str(orig_N)[:4])
    # Now get the number that is just bigger than orig_N
    # that has its first 4 digits equal to "factor"
    for factor in goodfactors:
        if factor > first4: break
    new_N = factor
    while new_N < orig_N:
        new_N *= 10
    # Finally, compare new_N to the closest power_of_two
    # greater than orig_N.  Take the closest.
    two_N = 2
    while two_N < orig_N:
        two_N *= 2
    if two_N < new_N: return two_N
    else: return new_N

def get_baryv(ra, dec, mjd, T, obs="AO"):
   """
   get_baryv(ra, dec, mjd, T):
     Determine the average barycentric velocity towards 'ra', 'dec'
       during an observation from 'obs'.  The RA and DEC are in the
       standard string format (i.e. 'hh:mm:ss.ssss' and 'dd:mm:ss.ssss').
       'T' is in sec and 'mjd' is (of course) in MJD.
   """
   tts = psr_utils.span(mjd, mjd+T/86400.0, 100)
   nn = len(tts)
   bts = numpy.zeros(nn, dtype=numpy.float64)
   vel = numpy.zeros(nn, dtype=numpy.float64)
   presto.barycenter(tts, bts, vel, nn, ra, dec, obs, "DE200")
   avgvel = numpy.add.reduce(vel)/nn
   return avgvel

def fix_fil_posn(fil_filenm, hdrlen, ra, dec):
    """
    fix_fil_posn(fil_filenm, hdrlen, ra, dec):
        Modify the filterbank header and update the RA and DEC
            fields using the values given as input.  ra and dec
            should be in 'HH:MM:SS.SSSS' and 'DD:MM:SS.SSSS' format.
            hdrlen is the length of the filterbank header as
            reported by PRESTO's 'readfile' or SIGPROC's 'header'.
    """
    newra = float(ra.replace(":", ""))
    newdec = float(dec.replace(":", ""))
    header = open(fil_filenm).read(hdrlen)
    ra_ptr = header.find("src_raj")+len("src_raj")
    dec_ptr = header.find("src_dej")+len("src_dej")
    filfile = open(fil_filenm, 'rb+')
    filfile.seek(ra_ptr)
    filfile.write(struct.pack('d', newra))
    filfile.seek(dec_ptr)
    filfile.write(struct.pack('d', newdec))
    filfile.close()

def read_db_posn(orig_filenm, beam):
    """
    read_db_posn(orig_filenm, beam):
        Find the original WAPP filename in the db_pointing_file
           and return the sexagesimal position strings for
           the choen beam in that file.  Return None if not found.
    """
    offset = beam % 2
    for line in open(db_pointing_file):
        sline = line.split()
        if sline[0].strip() == orig_filenm:
            ra_str = sline[2*offset+1].strip()
            dec_str = sline[2*offset+2].strip()
            return ra_str, dec_str
    return None

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
    subdmlist = numpy.asarray(subdmlist)
    return subdmlist

def find_closest_subbands(obs, subdms, DM):
    """
    find_closest_subbands(obs, subdms, DM):
        Return the basename of the closest set of subbands to DM
        given an obs_info class and a sorted array of the subdms.
    """
    subdm = subdms[numpy.fabs(subdms - DM).argmin()]
    return "subbands/%s_DM%.2f.sub[0-6]*"%(obs.basefilenm, subdm)

def timed_execute(cmd): 
    """
    timed_execute(cmd):
        Execute the command 'cmd' after logging the command
            to STDOUT.  Return the wall-clock amount of time
            the command took to execute.
    """
    sys.stdout.write("\n'"+cmd+"'\n")
    sys.stdout.flush()
    start = time.time()
    os.system(cmd)
    end = time.time()
    return end - start

def get_folding_command(cand, obs, subdms):
    """
    get_folding_command(cand, obs, subdms):
        Return a command for prepfold for folding the subbands using
            an obs_info instance, an array of the subdms, and a candidate 
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
    subfiles = find_closest_subbands(obs, subdms, cand.DM)
    p = 1.0 / cand.f
    if p < 0.002:
        Mp, Mdm, N = 2, 2, 24
        otheropts = "-npart 50"
    elif p < 0.05:
        Mp, Mdm, N = 2, 1, 50
        otheropts = "-npart 40 -pstep 1"
    elif p < 0.5:
        Mp, Mdm, N = 1, 1, 100
        otheropts = "-npart 30 -pstep 1 -dmstep 1"
    else:
        Mp, Mdm, N = 1, 1, 200
        otheropts = "-npart 30 -nopdsearch -pstep 1 -dmstep 1"
    return "prepfold -noxwin -accelcand %d -accelfile %s.cand -dm %.2f -o %s %s -n %d -npfact %d -ndmfact %d %s" % \
           (cand.candnum, cand.filename, cand.DM, outfilenm,
            otheropts, N, Mp, Mdm, subfiles)

class obs_info:
    """
    class obs_info(fil_filenm)
        A class describing the observation and the analysis.
    """
    def __init__(self, fil_filenm):
        self.fil_filenm = fil_filenm
        self.basefilenm = fil_filenm.rstrip(".fil")
        self.beam = int(self.basefilenm[-1])
        for line in os.popen("readfile %s"%fil_filenm):
            if "=" in line:
                key, val = line.split("=")
                if "Header" in key:
                    self.hdrlen = int(val)
                if "Original" in key:
                    split_orig_filenm = os.path.split(val.strip().strip("'"))[1].split(".")
                    self.orig_filenm = ".".join(split_orig_filenm[0:-2] +
                                                split_orig_filenm[-1:])
                if "MJD" in key:
                    self.MJD = float(val)
                if "RA" in key:
                    val = val.strip()
                    self.ra_string = val[:-9]+":"+val[-9:-7]+":"+val[-7:]
                if "DEC" in key:
                    val = val.strip()
                    self.dec_string = val[:-9]+":"+val[-9:-7]+":"+val[-7:]
                if "samples" in key:
                    self.orig_N = int(val)
                if "T_samp" in key:
                    self.dt = float(val) * 1e-6  # in sec
                if "Total Bandwidth" in key:
                    self.BW = float(val)
        self.orig_T = self.orig_N * self.dt
        self.N = choose_N(self.orig_N)
        self.T = self.N * self.dt
        # Update the RA and DEC from the database file if required
        newposn = read_db_posn(self.orig_filenm, self.beam)
        if newposn is not None:
            self.ra_string, self.dec_string = newposn
            # ... and use them to update the filterbank file
            fix_fil_posn(fil_filenm, self.hdrlen,
                         self.ra_string, self.dec_string)
        # Determine the average barycentric velocity of the observation
        self.baryv = get_baryv(self.ra_string, self.dec_string,
                               self.MJD, self.T, obs="AO")
        # Where to dump all the results
        # Directory structure is under the base_output_directory
        # according to base/MJD/filenmbase/beam
        self.outputdir = os.path.join(base_output_directory,
                                      str(int(self.MJD)),
                                      self.basefilenm[:-2],
                                      str(self.beam))
        # Figure out which host we are processing on
        self.hostname = socket.gethostname()
        # The fraction of the data recommended to be masked by rfifind
        self.masked_fraction = 0.0
        # Initialize our timers
        self.rfifind_time = 0.0
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
        report_file.write("%s was processed on %s\n"%(self.fil_filenm, self.hostname))
        report_file.write("Ending UTC time:  %s\n"%(time.asctime(time.gmtime())))
        report_file.write("Total wall time:  %.1f s (%.2f hrs)\n"%\
                          (self.total_time, self.total_time/3600.0))
        report_file.write("Fraction of data masked:  %.2f%%\n"%\
                          (self.masked_fraction*100.0))
        report_file.write("---------------------------------------------------------\n")
        report_file.write("          rfifind time = %7.1f sec (%5.2f%%)\n"%\
                          (self.rfifind_time, self.rfifind_time/self.total_time*100.0))
        report_file.write("       subbanding time = %7.1f sec (%5.2f%%)\n"%\
                          (self.subbanding_time, self.subbanding_time/self.total_time*100.0))
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
        self.sub_downsamp = self.downsamp / 2
        if self.sub_downsamp==0: self.sub_downsamp = 1
        # The total downsampling is:
        #   self.downsamp = self.sub_downsamp * self.dd_downsamp
        if self.downsamp==1: self.dd_downsamp = 1
        else: self.dd_downsamp = 2
        self.sub_dmstep = self.dmsperpass * self.dmstep
        self.dmlist = []  # These are strings for comparison with filenames
        self.subdmlist = []
        for ii in range(self.numpasses):
            self.subdmlist.append("%.2f"%(self.lodm + (ii+0.5)*self.sub_dmstep))
            lodm = self.lodm + ii * self.sub_dmstep
            dmlist = ["%.2f"%dm for dm in \
                      numpy.arange(self.dmsperpass)*self.dmstep + lodm]
            self.dmlist.append(dmlist)

# Create our de-dispersion plans (for 100MHz WAPPs)
# The following are the "optimal" values for the 100MHz
# survey.  It keeps the total dispersive smearing (i.e.
# not counting scattering <1 ms up to a DM of ~600 pc cm^-3
ddplans = []
if (1):
    # The values here are:       lodm dmstep dms/call #calls #subbands downsamp
    ddplans.append(dedisp_plan(   0.0,   0.3,      24,    26,       32,       1))
    ddplans.append(dedisp_plan( 187.2,   0.5,      24,    10,       32,       2))
    ddplans.append(dedisp_plan( 307.2,   1.0,      24,    11,       32,       4))
    ddplans.append(dedisp_plan( 571.2,   3.0,      24,     6,       32,       8))
else: # faster option that sacrifices a small amount of time resolution at the lowest DMs
    # The values here are:       lodm dmstep dms/call #calls #subbands downsamp
    ddplans.append(dedisp_plan(   0.0,   0.5,      22,    21,       32,       1))
    ddplans.append(dedisp_plan( 231.0,   0.5,      24,     6,       32,       2))
    ddplans.append(dedisp_plan( 303.0,   1.0,      24,    11,       32,       4))
    ddplans.append(dedisp_plan( 567.0,   3.0,      24,     7,       32,       8))
    
def main(fil_filenm, workdir):

    # Change to the specified working directory
    os.chdir(workdir)

    # Get information on the observation and the jbo
    job = obs_info(fil_filenm)
    if job.T < low_T_to_search:
        print "The observation is too short (%.2f s) to search."%job.T
        sys.exit()
    job.total_time = time.time()
    
    # Use whatever .zaplist is found in the current directory
    default_zaplist = glob.glob("*.zaplist")[0]

    # Make sure the output directory (and parent directories) exist
    try:
        os.makedirs(job.outputdir)
    except: pass

    # Create a directory to hold all the subbands
    try:
        os.makedirs("subbands")
    except: pass
    
    print "\nBeginning PALFA search of '%s'"%job.fil_filenm
    print "UTC time is:  %s"%(time.asctime(time.gmtime()))

    # rfifind the filterbank file
    cmd = "rfifind -time %.17g -o %s %s > %s_rfifind.out"%\
          (rfifind_chunk_time, job.basefilenm,
           job.fil_filenm, job.basefilenm)
    job.rfifind_time += timed_execute(cmd)
    maskfilenm = job.basefilenm + "_rfifind.mask"
    # Find the fraction that was suggested to be masked
    # Note:  Should we stop processing if the fraction is
    #        above some large value?  Maybe 30%?
    job.masked_fraction = find_masked_fraction(job)
    
    # Iterate over the stages of the overall de-dispersion plan
    dmstrs = []
    for ddplan in ddplans:

        # Iterate over the individual passes through the .fil file
        for passnum in range(ddplan.numpasses):
            subbasenm = "%s_DM%s"%(job.basefilenm, ddplan.subdmlist[passnum])

            # Create a set of subbands
            cmd = "prepsubband -sub -subdm %s -downsamp %d -nsub %d -mask %s -o subbands/%s %s > %s.subout"%\
                  (ddplan.subdmlist[passnum], ddplan.sub_downsamp,
                   ddplan.numsub, maskfilenm, job.basefilenm,
                   job.fil_filenm, subbasenm)
            job.subbanding_time += timed_execute(cmd)
            
            # Now de-disperse using the subbands
            cmd = "prepsubband -lodm %.2f -dmstep %.2f -numdms %d -downsamp %d -numout %d -o %s subbands/%s.sub[0-9]* > %s.prepout"%\
                  (ddplan.lodm+passnum*ddplan.sub_dmstep, ddplan.dmstep,
                   ddplan.dmsperpass, ddplan.dd_downsamp, job.N/ddplan.downsamp,
                   job.basefilenm, subbasenm, subbasenm)
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
                try:
                    shutil.copy(basenm+".singlepulse", job.outputdir)
                except: pass

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
                cmd = "accelsearch -numharm %d -sigma %f -zmax %d -flo %f %s"%\
                      (lo_accel_numharm, lo_accel_sigma, lo_accel_zmax, lo_accel_flo, fftnm)
                job.lo_accelsearch_time += timed_execute(cmd)
                try:
                    os.remove(basenm+"_ACCEL_%d.txtcand"%lo_accel_zmax)
                except: pass
                try:  # This prevents errors if there are no cand files to copy
                    shutil.copy(basenm+"_ACCEL_%d.cand"%lo_accel_zmax, job.outputdir)
                    shutil.copy(basenm+"_ACCEL_%d"%lo_accel_zmax, job.outputdir)
                except: pass
        
                # Do the high-acceleration search
                cmd = "accelsearch -numharm %d -sigma %f -zmax %d -flo %f %s"%\
                      (hi_accel_numharm, hi_accel_sigma, hi_accel_zmax, hi_accel_flo, fftnm)
                job.hi_accelsearch_time += timed_execute(cmd)
                try:
                    os.remove(basenm+"_ACCEL_%d.txtcand"%hi_accel_zmax)
                except: pass
                try:  # This prevents errors if there are no cand files to copy
                    shutil.copy(basenm+"_ACCEL_%d.cand"%hi_accel_zmax, job.outputdir)
                    shutil.copy(basenm+"_ACCEL_%d"%hi_accel_zmax, job.outputdir)
                except: pass

                # Remove the .dat and .fft files
                try:
                    os.remove(datnm)
                except: pass
                try:
                    os.remove(fftnm)
                except: pass

    # Make the single-pulse plot
    cmd = "single_pulse_search.py -t %f *.singlepulse"%singlepulse_plot_SNR
    job.singlepulse_time += timed_execute(cmd)

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
        os.system(cmd)
    except: pass

    job.sifting_time = time.time() - job.sifting_time

    # Fold the best candidates

    subdms = get_all_subdms(ddplans)
    cands_folded = 0
    for cand in all_accel_cands:
        if cands_folded == max_cands_to_fold:
            break
        if cand.sigma > to_prepfold_sigma:
            job.folding_time += timed_execute(get_folding_command(cand, job, subdms))
            cands_folded += 1

    # Now step through the .ps files and convert them to .png and gzip them

    psfiles = glob.glob("*.ps")
    for psfile in psfiles:
        if "singlepulse" in psfile:
            # For some reason the singlepulse files don't transform nicely...
            epsfile = psfile.replace(".ps", ".eps")
            os.system("eps2eps "+psfile+" "+epsfile)
            os.system("pstoimg -density 100 -crop a "+epsfile)
            try:
                os.remove(epsfile)
            except: pass
        else:
            os.system("pstoimg -density 100 -flip cw "+psfile)
        os.system("gzip "+psfile)
    
    # NOTE:  need to add database commands

    # And finish up

    job.total_time = time.time() - job.total_time
    print "\nFinished"
    print "UTC time is:  %s"%(time.asctime(time.gmtime()))

    # Write the job report

    job.write_report(job.basefilenm+".report")
    job.write_report(os.path.join(job.outputdir, job.basefilenm+".report"))

    # Copy all the important stuff to the output directory
    try:
        cmd = "cp *rfifind.[bimors]* *.pfd *.ps.gz *.png "+job.outputdir
        os.system(cmd)
    except: pass
    
if __name__ == "__main__":
    # Arguments to the search program are
    # sys.argv[1] = filterbank file name
    # sys.argv[2] = working directory name
    fil_filenm = sys.argv[1]
    workdir = sys.argv[2]
    main(fil_filenm, workdir)
