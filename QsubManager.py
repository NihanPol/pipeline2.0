import config
from PipelineQueueManager import PipelineQueueManager
import PBSQuery

class Qsub(PipelineQueueManager):
    
    @staticmethod
    def submit(files_str_array, output_dir_str):
        """Must return a unique identifier for the job"""
        cmd = 'qsub -V -v DATAFILES="%s",OUTDIR="%s" -l %s -N %s -e %s search.py' % \
                            (','.join(self.datafiles), self.get_output_dir(), config.resource_list, \
                                    config.job_basename, 'qsublog')
        pipe = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,stdin=subprocess.PIPE)
        jobid = pipe.communicate()[0]
        pipe.stdin.close()
        if not jobid:
            return None
        return jobid.rstrip()
    
    @staticmethod
    def is_running(jobid_str):
        """Must return True/False wheather the job is in the Queue or not
            respectively
        """
        batch = PBSQuery.PBSQuery().getjobs()
        if jobid_str in batch:
            return True
        else:
            return False
    
    @staticmethod
    def delete(jobid_str):
        """Must garantee the removal of the job from the Queue"""
        cmd = "qdel %s" % jobid_str
        pipe = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,stdin=subprocess.PIPE)
        response = pipe.communicate()[0]
        pipe.stdin.close()
        batch = PBSQuery.PBSQuery().getjobs()
        if not (self.jobid in batch) or 'E' in batch[self.jobid]['job_state']:
            self.jobid = None
            return True
        return False
    
    @staticmethod
    def status():
        """Must return a tuple of number of jobs running and queued for the pipeline
        Note:
        """
        numrunning = 0
        numqueued = 0
        batch = PBSQuery.PBSQuery().getjobs()
        for j in batch.keys():
            if batch[j]['Job_Name'][0].startswith(config.job_basename):
                if 'R' in batch[j]['job_state']:
                    numrunning += 1
                elif 'Q' in batch[j]['job_state']:
                    numqueued += 1
        return (numrunning, numqueued)