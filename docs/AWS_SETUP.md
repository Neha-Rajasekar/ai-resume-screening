# AWS deployment guide

Step-by-step setup of the cloud side of the project on a **new AWS Free plan account**,
in the **Sydney region (`ap-southeast-2`)**. Run the commands in **AWS CloudShell**
(the `>_` icon in the AWS console top bar): it already has the AWS CLI logged in as you,
so nothing needs installing on Windows.

```
                    ┌──────────── GitHub ─────────────┐
   git push ──────► │ Actions: test → build → deploy  │──── docker push ───► ghcr.io   
                    └───────────────┬─────────────────┘                          │
                                    │ SSH: docker pull + run                     │
                                    ▼                                            │
  Recruiter ──HTTP:80──► ┌──────── EC2 (t3.small) ────────┐ ◄────────────────────┘
   browser               │ Docker container               │
                         │  Flask + gunicorn + MiniLM     │──► RDS MySQL (private)
                         │  IAM role (no keys stored)     │──► S3  (dataset, ranked CSVs)
                         └────────────────────────────────┘──► SNS (email: "top 30 ready")
```

---

## 0. Before anything: protect your credits

1. Console → **Billing and Cost Management → Budgets → Create budget** → *Zero spend* or a *Monthly cost budget* of $20 with email alerts.
   Setting a budget is also one of the Free plan activities that earns **$20 extra credit**.
2. Pick region **Asia Pacific (Sydney) ap-southeast-2** (top-right of the console) and use it for everything.
3. Do **not** click "Upgrade plan". On the Free plan AWS cannot charge your card.

## 1. Variables (paste once per CloudShell session)

```bash
export AWS_REGION=ap-southeast-2
export NAME=resume                                   # prefix for every resource
export BUCKET=resume-screening-$(aws sts get-caller-identity --query Account --output text)
export DB_PASS='ChooseAStrongPassword123'            # 8+ chars, no @ / " or spaces
export MY_EMAIL='you@example.com'                    # receives the SNS alerts
```

## 2. S3 bucket (resume dataset + ranked shortlists)

```bash
aws s3api create-bucket --bucket $BUCKET --region $AWS_REGION \
  --create-bucket-configuration LocationConstraint=$AWS_REGION
aws s3api put-public-access-block --bucket $BUCKET \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

Upload the dataset: in CloudShell click **Actions → Upload file** → pick `resume_data.csv`, then

```bash
aws s3 cp resume_data.csv s3://$BUCKET/dataset/resume_data.csv
aws s3 ls s3://$BUCKET/dataset/
```

## 3. SNS topic (email alert when a shortlist is ready)

```bash
export TOPIC_ARN=$(aws sns create-topic --name resume-shortlist-ready --query TopicArn --output text)
aws sns subscribe --topic-arn $TOPIC_ARN --protocol email --notification-endpoint $MY_EMAIL
echo $TOPIC_ARN
```

Open the email from AWS and click **Confirm subscription**, otherwise nothing is delivered.

## 4. Security groups (firewall)

```bash
export VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)

# App server: web traffic from anyone, SSH for GitHub Actions deployments (key-only login)
export APP_SG=$(aws ec2 create-security-group --group-name $NAME-app-sg \
  --description "Resume app EC2" --vpc-id $VPC_ID --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $APP_SG --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $APP_SG --protocol tcp --port 22 --cidr 0.0.0.0/0

# Database: MySQL reachable ONLY from the app server's security group
export DB_SG=$(aws ec2 create-security-group --group-name $NAME-db-sg \
  --description "Resume RDS MySQL" --vpc-id $VPC_ID --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $DB_SG --protocol tcp --port 3306 --source-group $APP_SG
```

Port 22 is open to all because GitHub's runners use changing IPs; login still needs your private key.

## 5. RDS MySQL database

```bash
aws rds create-db-instance \
  --db-instance-identifier $NAME-db \
  --engine mysql \
  --db-instance-class db.t4g.micro \
  --allocated-storage 20 --storage-type gp2 \
  --master-username admin --master-user-password "$DB_PASS" \
  --db-name resumedb \
  --vpc-security-group-ids $DB_SG \
  --no-publicly-accessible --no-multi-az \
  --backup-retention-period 1

# Takes ~5-10 minutes. Wait, then read the endpoint:
aws rds wait db-instance-available --db-instance-identifier $NAME-db
export DB_HOST=$(aws rds describe-db-instances --db-instance-identifier $NAME-db \
  --query 'DBInstances[0].Endpoint.Address' --output text)
echo $DB_HOST
```

If `db.t4g.micro` is refused, use `db.t3.micro`.

## 6. IAM role for EC2 (lets the app use S3 and SNS without any keys in code)

```bash
cat > trust.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
cat > policy.json <<EOF
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject"],"Resource":"arn:aws:s3:::$BUCKET/*"},
  {"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::$BUCKET"},
  {"Effect":"Allow","Action":"sns:Publish","Resource":"$TOPIC_ARN"}]}
EOF
aws iam create-role --role-name $NAME-ec2-role --assume-role-policy-document file://trust.json
aws iam put-role-policy --role-name $NAME-ec2-role --policy-name app-access --policy-document file://policy.json
aws iam create-instance-profile --instance-profile-name $NAME-ec2-profile
aws iam add-role-to-instance-profile --instance-profile-name $NAME-ec2-profile --role-name $NAME-ec2-role
```

This is least privilege: the app can only read/write its own bucket and publish to its own topic.

## 7. EC2 instance (runs the Docker container)

```bash
# SSH key pair: download resume-key.pem afterwards (Actions → Download file) and keep it safe
aws ec2 create-key-pair --key-name $NAME-key --query KeyMaterial --output text > $NAME-key.pem
chmod 400 $NAME-key.pem

# Boot script: install Docker and add 2 GB swap (extra safety for the ML model)
cat > userdata.sh <<'EOF'
#!/bin/bash
dnf install -y docker
systemctl enable --now docker
usermod -aG docker ec2-user
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
EOF

sleep 10   # give the new instance profile a moment to become usable
export INSTANCE_ID=$(aws ec2 run-instances \
  --image-id resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --instance-type t3.small \
  --key-name $NAME-key \
  --security-group-ids $APP_SG \
  --iam-instance-profile Name=$NAME-ec2-profile \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=20,VolumeType=gp3}' \
  --user-data file://userdata.sh \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME-app}]" \
  --query 'Instances[0].InstanceId' --output text)

aws ec2 wait instance-running --instance-ids $INSTANCE_ID
export EC2_IP=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo $EC2_IP
```

`t3.small` (2 GB RAM) is Free-plan eligible and comfortable for MiniLM. To double-check what your
account allows: `aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true --query "InstanceTypes[*].InstanceType"`.

## 8. App configuration on the EC2 instance

Create the env file the container reads (still in CloudShell):

```bash
cat > app.env <<EOF
DATABASE_URL=mysql+pymysql://admin:$DB_PASS@$DB_HOST:3306/resumedb?charset=utf8mb4
AWS_REGION=$AWS_REGION
S3_BUCKET=$BUCKET
SNS_TOPIC_ARN=$TOPIC_ARN
PUBLIC_URL=http://$EC2_IP
SECRET_KEY=$(openssl rand -hex 32)
EOF
scp -o StrictHostKeyChecking=no -i $NAME-key.pem app.env ec2-user@$EC2_IP:/home/ec2-user/app.env
ssh -i $NAME-key.pem ec2-user@$EC2_IP 'chmod 600 app.env && docker --version'
```

## 9. GitHub repository + secrets (CI/CD)

The pipeline stores the Docker image in **GitHub Container Registry (ghcr.io)**, so no separate
registry account is needed: the workflow's built-in `GITHUB_TOKEN` pushes the image and is passed to
EC2 only for the duration of the deploy to pull it.

1. Push this project folder to a GitHub repository, branch `main` (workflow at `.github/workflows/ci-cd.yml`).
2. In the GitHub repo: **Settings -> Secrets and variables -> Actions -> New repository secret**:

| Secret | Value |
|---|---|
| `EC2_HOST` | the `$EC2_IP` value |
| `EC2_SSH_KEY` | full contents of `resume-key.pem` (incl. BEGIN/END lines) |

3. **Settings -> Environments -> New environment** named `production` (optionally add yourself as a required reviewer).
4. Push any commit (or **Actions -> CI/CD -> Run workflow**). The pipeline runs tests, builds the image, pushes it
   to ghcr.io, SSHes into EC2 and starts the container.

## 10. Load the dataset into RDS (once, from EC2)

```bash
ssh -i $NAME-key.pem ec2-user@$EC2_IP \
  "docker exec resume-app python scripts/load_db.py --csv s3://$BUCKET/dataset/resume_data.csv"
```

Expected: `Extracted 344 unique candidates, 28 jobs, 9544 labelled pairs`. The app embeds the resumes
on the first ranking request (~30 s once; cached afterwards). If you ever re-load the data while the
app is running, run `docker restart resume-app` so it re-reads the candidates.

Open `http://<EC2_IP>` → pick a job → **Rank candidates**. Check your email for the SNS alert and
`aws s3 ls s3://$BUCKET/rankings/` for the stored CSV.

---

## Useful commands for the demo / viva

```bash
ssh -i resume-key.pem ec2-user@$EC2_IP
docker ps                                   # container status + health
docker logs --tail 50 resume-app            # app logs
curl localhost/health                       # JSON health check
aws s3 ls s3://$BUCKET --recursive          # stored dataset + shortlists
```

## Saving credits on days you are not working

```bash
aws ec2 stop-instances --instance-ids $INSTANCE_ID
aws rds stop-db-instance --db-instance-identifier $NAME-db     # auto-restarts after 7 days!
# later
aws rds start-db-instance --db-instance-identifier $NAME-db
aws ec2 start-instances --instance-ids $INSTANCE_ID
```

After a stop/start the EC2 **public IP changes**: update the `EC2_HOST` secret and `PUBLIC_URL` in `app.env`.

## Teardown after evaluation (stops all charges)

```bash
aws ec2 terminate-instances --instance-ids $INSTANCE_ID
aws rds delete-db-instance --db-instance-identifier $NAME-db --skip-final-snapshot --delete-automated-backups
aws s3 rm s3://$BUCKET --recursive && aws s3api delete-bucket --bucket $BUCKET
aws sns delete-topic --topic-arn $TOPIC_ARN
aws ec2 wait instance-terminated --instance-ids $INSTANCE_ID
aws ec2 delete-security-group --group-id $APP_SG
aws rds wait db-instance-deleted --db-instance-identifier $NAME-db && aws ec2 delete-security-group --group-id $DB_SG
aws iam remove-role-from-instance-profile --instance-profile-name $NAME-ec2-profile --role-name $NAME-ec2-role
aws iam delete-instance-profile --instance-profile-name $NAME-ec2-profile
aws iam delete-role-policy --role-name $NAME-ec2-role --policy-name app-access
aws iam delete-role --role-name $NAME-ec2-role
aws ec2 delete-key-pair --key-name $NAME-key
```

If CloudShell was closed, the `$VARIABLES` are gone: re-run step 1 and look up the IDs in the console.
