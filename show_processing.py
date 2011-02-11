import jobtracker


def main():
    processing = jobtracker.query("SELECT *,job_submits.created_at as job_submit_created_at FROM job_submits,jobs,job_files,downloads WHERE job_submits.status='running' AND jobs.id=job_submits.job_id AND job_files.job_id=jobs.id AND downloads.id=job_files.file_id")
    for job in processing:
        print "%s\t%s\t%s" % (job['filename'],job['queue_id'],job['job_submit_created_at'])
    
    print "\nTotal: %u" % len(processing)


if __name__ == "__main__":
    main()
