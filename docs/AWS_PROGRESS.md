# AWS deployment progress (account 813559108695, region ap-southeast-2 Sydney)

Done (all free, nothing billing hourly yet) - 20 Oct 2026:
- [x] S3 bucket: resume-screening-813559108695 (public access blocked); dataset at s3://resume-screening-813559108695/dataset/resume_data.csv (17,004,490 bytes)
- [x] SNS topic: arn:aws:sns:ap-southeast-2:813559108695:resume-shortlist-ready (email subscription confirmed)
- [x] VPC (default): vpc-05496f4b5e548b9d2
- [x] Security groups: resume-app-sg sg-0421b71f01636e8bc (80, 22) · resume-db-sg sg-0d0453ea258edeb2c (3306 from app SG)
- [x] IAM role resume-ec2-role + instance profile resume-ec2-profile (S3 Get/Put/List own bucket, SNS Publish own topic)

Next:
- [x] Step 7 RDS MySQL db.t4g.micro resume-db, endpoint resume-db.cf6qqmiempar.ap-southeast-2.rds.amazonaws.com: available 20 Oct 15:24 IST (BILLS HOURLY ~$0.025/hr)
- [x] Step 8 EC2 t3.small i-0a27d4aef9cb8220e, public IP 54.66.145.64, key resume-key.pem (in Downloads) - launched 20 Oct 15:20 IST (BILLS HOURLY ~$0.033/hr)
- [ ] app.env on EC2, GitHub repo + secrets, first deploy, load dataset into RDS

Paste in CloudShell after every restart:
export AWS_REGION=ap-southeast-2 NAME=resume AWS_PAGER=""
export BUCKET=resume-screening-813559108695
export TOPIC_ARN=arn:aws:sns:ap-southeast-2:813559108695:resume-shortlist-ready
export VPC_ID=vpc-05496f4b5e548b9d2 APP_SG=sg-0421b71f01636e8bc DB_SG=sg-0d0453ea258edeb2c
export INSTANCE_ID=i-0a27d4aef9cb8220e EC2_IP=54.66.145.64
export DB_HOST=resume-db.cf6qqmiempar.ap-southeast-2.rds.amazonaws.com
export DB_PASS='<your db password>'
