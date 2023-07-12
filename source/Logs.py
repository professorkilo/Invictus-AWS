import boto3, os, time

from source.utils import *


class Logs:
    bucket = ""
    region = ""

    def __init__(self, region, dl):
        if dl:
            print("ff")
        else:
            # self.bucket = create_s3_if_not_exists(region, LOGS_BUCKET)
            print("==")

    def self_test(self):
        print("Logs work")

    def execute(self, services):
        print("Log Extraction")
        self.services = services

        self.get_logs_s3()
        self.get_logs_wafv2()
        self.get_logs_vpc()
        self.get_logs_elasticbeanstalk()

        self.get_logs_route53()
        self.get_logs_ec2()
        self.get_logs_rds()

        self.get_logs_cloudwatch()
        self.get_logs_guardduty()
        self.get_logs_inspector2()
        self.get_logs_maciev2()

        self.get_logs_cloudtrail_logs()
        self.get_logs_cloudtrail_trails()

    def get_logs_guardduty(self):
        guardduty_list = self.services["guardduty"]

        if guardduty_list["count"] == -1:
            response = try_except(GUARDDUTY_CLIENT.list_detectors)
            response.pop("ResponseMetadata", None)
            response = fix_json(response)
            detectors_ids = response.get("DetectorIds", [])

            if len(detectors_ids) == 0:
                self.display_progress(0, "guardduty")
                return

        elif guardduty_list["count"] == 0:
            self.display_progress(0, "guardduty")
            return
        else:
            detector_ids = guardduty_list["ids"]

        findings_data = {}
        for detector in detector_ids:
            findings = try_except(GUARDDUTY_CLIENT.list_findings, DetectorId=detector)
            findings = findings["FindingIds"]

            response = try_except(
                GUARDDUTY_CLIENT.get_findings, DetectorId=detector, FindingIds=findings
            )
            response.pop("ResponseMetadata", None)
            response = fix_json(response)
            findings_data[detector] = response

        results = []
        results.append(
            create_command(
                "guardduty get-findings --detector-id <id> --findings-id <ids>",
                findings_data,
            )
        )

        self.display_progress(len(results), "guardduty")
        write_s3(
            self.bucket,
            LOGS_KEY + "guardduty/guardduty.json",
            json.dumps(results, indent=4, default=str),
        )

    def cloudtrail_lookup(self, token=None):
        if token is None:
            response = CLOUDTRAIL_CLIENT.lookup_events(
                MaxResults=50,
            )
        else:
            response = CLOUDTRAIL_CLIENT.lookup_events(
                MaxResults=50,
                NextToken=token,
            )
        return response

    def get_logs_cloudtrail_logs(self):
        cloudtrail_list = self.services["cloudtrail-logs"]

        if cloudtrail_list["count"] == -1:
            response = self.cloudtrail_lookup()

            if len(response["Events"]) == 0:
                self.display_progress(0, "cloudtrail")
                return
            else:
                events = response["Events"]
                token = response.get("NextToken")
                while token:
                    response = self.cloudtrail_lookup(token)
                    events.append(response["Events"])
                    token = response.get("NextToken")

                logs = fix_json(events)

        elif cloudtrail_list["count"] == 0:
            self.display_progress(0, "cloudtrail")
            return

        # write_s3(
        #    self.bucket,
        #    LOGS_KEY + "cloudtrail/cloudtrail.json",
        #    json.dumps(logs, indent=4, default=str),
        # )
        self.display_progress(1, "cloudtrail-logs")

    def get_logs_cloudtrail_trails(self):
        cloudtrail_list = self.services["cloudtrail"]

        if cloudtrail_list["count"] == -1:
            response = try_except(CLOUDTRAIL_CLIENT.list_trails)
            response.pop("ResponseMetadata", None)
            response = fix_json(response)
            trails = response.get("Trails", [])

            if len(trails) == 0:
                self.display_progress(0, "cloudtrail")
                return

            trails_name = []
            for el in trails:
                trails_name.append(el["Name"])

        elif cloudtrail_list["count"] == 0:
            self.display_progress(0, "cloudtrail")
            return
        else:
            trails_name = cloudtrail_list["elements"]

        for trail_name in trails_name:
            response = try_except(CLOUDTRAIL_CLIENT.get_trail, Name=trail_name)
            if "Trail" not in response or "S3BucketName" not in response["Trail"]:
                continue
            src_bucket = response["Trail"]["S3BucketName"]
            self.copy_s3_bucket(src_bucket, self.bucket, "cloudtrail/" + trail_name)

        self.display_progress(1, "cloudtrail-trails")

    def get_logs_wafv2(self):
        waf_list = self.services["wafv2"]

        if waf_list["count"] == -1:
            response = try_except(WAF_CLIENT.list_web_acls, Scope="REGIONAL")
            response.pop("ResponseMetadata", None)
            wafs = response.get("WebACLs", [])

            identifiers = []
            for el in wafs:
                identifiers.append(el["ARN"])

            if len(identifiers) == 0:
                self.display_progress(0, "wafv2")
                return

        elif waf_list["count"] == 0:
            self.display_progress(0, "wafv2")
            return
        else:
            identifiers = waf_list["ids"]

        cnt = 0

        for arn in identifiers:
            logging = try_except(WAF_CLIENT.get_logging_configuration, ResourceArn=arn)
            if "LoggingConfiguration" in logging:
                destinations = logging["LoggingConfiguration"]["LogDestinationConfigs"]
                for destination in destinations:
                    if "s3" in destination:
                        bucket = destination.split(":")[-1]
                        src_bucket = bucket.split("/")[0]
                        self.copy_s3_bucket(src_bucket, self.bucket, "wafv2")
                        cnt += 1

        self.display_progress(cnt, "wafv2")

    def get_logs_vpc(self):
        vpc_list = self.services["vpc"]

        if vpc_list["count"] == -1:
            response = try_except(EC2_CLIENT.describe_vpcs)
            response.pop("ResponseMetadata", None)
            response = fix_json(response)
            vpcs = response.get("Vpcs", [])

            if len(vpcs) == 0:
                self.display_progress(0, "vpc")
                return

        elif vpc_list["count"] == 0:
            self.display_progress(0, "vpc")
            return

        response = try_except(EC2_CLIENT.describe_flow_logs)
        flow_logs = response.get("FlowLogs", [])
        cnt = 0

        for flow_log in flow_logs:
            if "s3" in flow_log["LogDestinationType"]:
                bucket = flow_log["LogDestination"].split(":")[-1]
                src_bucket = bucket.split("/")[0]
                self.copy_s3_bucket(src_bucket, self.bucket, "vpc")
                cnt += 1
        self.display_progress(cnt, "vpc")

    def get_logs_elasticbeanstalk(self):
        eb = boto3.client("elasticbeanstalk")

        eb_list = self.services["elasticbeanstalk"]

        if eb_list["count"] == -1:
            response = try_except(eb.describe_environments)
            response.pop("ResponseMetadata", None)
            response = fix_json(response)
            environments = response.get("Environments", [])

            if len(environments) == 0:
                self.display_progress(0, "elasticbeanstalk")
                return

        elif eb_list["count"] == 0:
            self.display_progress(0, "elasticbeanstalk")
            return
        else:
            environments = eb_list["elements"]

        for environment in environments:
            name = environment.get("EnvironmentName", "")
            if name == "":
                continue

            response = try_except(
                eb.request_environment_info, EnvironmentName=name, InfoType="bundle"
            )
            response = fix_json(response)
            time.sleep(60)

            response = try_except(
                eb.retrieve_environment_info, EnvironmentName=name, InfoType="bundle"
            )
            response = fix_json(response)

            urls = response["EnvironmentInfo"]
            if len(urls) > 0:
                url = urls[-1]
                url = url["Message"]

            filename = name + ".zip"
            r = requests.get(url)
            with open(filename, "wb") as f:
                f.write(r.content)

            key = "eb/" + name + ".zip"
            writefile_s3(self.bucket, key, filename)
            os.remove(filename)

        self.display_progress(len(environments), "elasticbeanstalk")
        return

    def get_logs_cloudwatch(self):
        cloudwatch_list = self.services["cloudwatch"]

        if cloudwatch_list["count"] == -1:
            response = try_except(CLOUDWATCH_CLIENT.list_dashboards)
            response.pop("ResponseMetadata", None)
            response = fix_json(response)
            dashboards = response.get("DashboardEntries", [])

            if len(dashboards) == 0:
                self.display_progress(0, "cloudwatch")
                return

        elif cloudwatch_list["count"] == 0:
            self.display_progress(0, "cloudwatch")
            return
        else:
            dashboards = cloudwatch_list["elements"]

        dashboards_data = {}
        for dashboard in dashboards:
            dashboard_name = dashboard.get("DashboardName", "")
            if dashboard_name == "":
                continue
            response = try_except(
                CLOUDWATCH_CLIENT.get_dashboard, DashboardName=dashboard_name
            )
            response.pop("ResponseMetadata", None)
            dashboards_data[dashboard_name] = fix_json(response)

        response = try_except(CLOUDWATCH_CLIENT.list_metrics)
        response.pop("ResponseMetadata", None)
        metrics = fix_json(response)

        response = try_except(CLOUDWATCH_CLIENT.describe_alarms)
        response.pop("ResponseMetadata", None)
        alarms = fix_json(response)

        results = []
        results.append(
            create_command("cloudwatch get-dashboard --name <name>", dashboards_data)
        )
        results.append(create_command("cloudwatch list-metrics --name <name>", metrics))
        results.append(
            create_command("cloudwatch describe-alarms --name <name>", alarms)
        )

        self.display_progress(len(results), "cloudwatch")
        write_s3(
            self.bucket,
            LOGS_KEY + "cloudwatch/cloudwatch.json",
            json.dumps(results, indent=4, default=str),
        )
        return

    """
    src_bucket : bucket where all the s3 logging are stored
    dst_bucket : bucket used in incident response
    key_part : part of the logs' path
    """

    def copy_s3_bucket(self, src_bucket, dst_bucket, key_part):
        s3res = boto3.resource("s3")
        s3api = boto3.client("s3")

        response = try_except(s3api.list_objects_v2, Bucket=src_bucket)
        contents = response.get("Contents", [])

        for key in contents:
            copy_source = {"Bucket": src_bucket, "Key": key["Key"]}
            new_key = LOGS_KEY + key_part + "/" + src_bucket + "/" + key["Key"]
            try_except(s3res.meta.client.copy, copy_source, dst_bucket, new_key)

    def get_logs_s3(self):
        s3_list = self.services["s3"]

        if s3_list["count"] == -1:
            # if no listing of the s3 buckets was done before
            response = try_except(S3_CLIENT.list_buckets)  # buckets' listing
            response.pop("ResponseMetadata", None)
            buckets = fix_json(response)
            elements = buckets.get("Buckets", [])

            if len(elements) == 0:
                self.display_progress(0, "s3")
                return

        elif s3_list["count"] == 0:
            # if there is not bucket at all
            self.display_progress(0, "s3")
            return
        else:
            elements = s3_list["elements"]

        cnt = 0

        for bucket in elements:
            name = bucket["Name"]

            logging = try_except(S3_CLIENT.get_bucket_logging, Bucket=name)
            if "LoggingEnabled" in logging:
                target = logging["LoggingEnabled"]["TargetBucket"]
                bucket = target.split(":")[-1]
                src_bucket = bucket.split("/")[0]
                self.copy_s3_bucket(src_bucket, self.bucket, "s3")
                cnt += 1

        self.display_progress(cnt, "s3")

    def get_logs_inspector2(self):
        inspector_list = self.services["inspector"]

        if inspector_list["count"] == -1:
            response = try_except(INSPECTOR_CLIENT.list_coverage)
            response.pop("ResponseMetadata", None)
            coverage = fix_json(response)

            covered = coverage.get("coveredResources", [])

            if len(covered) == 0:
                self.display_progress(0, "inspector")
                return

        elif inspector_list["count"] == 0:
            self.display_progress(0, "inspector")
            return

        response = try_except(INSPECTOR_CLIENT.list_findings)
        response.pop("ResponseMetadata", None)
        get_findings = fix_json(response)

        response = try_except(
            INSPECTOR_CLIENT.list_finding_aggregations, aggregationType="TITLE"
        )
        response.pop("ResponseMetadata", None)
        get_grouped_findings = fix_json(response)

        results = []
        results.append(create_command("aws inspector2 list-findings", get_findings))
        results.append(
            create_command(
                "aws inspector2 list-finding-aggregations --aggregation-type TITLE",
                get_grouped_findings,
            )
        )

        self.display_progress(len(results), "inspector")
        write_s3(
            self.bucket,
            LOGS_KEY + "inspector/inspector.json",
            json.dumps(results, indent=4, default=str),
        )

    def get_logs_maciev2(self):
        macie_list = self.services["macie"]

        if macie_list["count"] == -1:
            response = try_except(MACIE_CLIENT.describe_buckets)
            response.pop("ResponseMetadata", None)
            response = fix_json(response)
            elements = response.get("buckets", [])

            if len(elements) == 0:
                self.display_progress(0, "macie")
                return
        elif macie_list["count"] == 0:
            self.display_progress(0, "macie")
            return

        response = try_except(MACIE_CLIENT.list_findings)
        response.pop("ResponseMetadata", None)
        get_list_findings = fix_json(response)

        response = try_except(
            MACIE_CLIENT.get_findings,
            findingIds=get_list_findings.get("findingIds", []),
        )
        response.pop("ResponseMetadata", None)
        findings = fix_json(response)

        results = []
        results.append(create_command("aws macie2 list-findings", get_list_findings))
        results.append(
            create_command("aws macie2 get-findings --finding-ids <ID>", findings)
        )

        self.display_progress(len(results), "macie")
        write_s3(
            self.bucket,
            LOGS_KEY + "macie/macie.json",
            json.dumps(results, indent=4, default=str),
        )

    def create_json(self):
        file_json = {
            "Version": "2012-10-17",
            "Statement": {
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            },
        }

        with open(ROLE_JSON, "w") as f:
            json.dump(file_json, f)
        with open(ROLE_JSON, "r") as fr:
            data = fr.read()

        return data

    def create_ssm_role(self):
        data = self.create_json()
        iam = boto3.client("iam")
        role_name = "SSM_IR_Extraction01"
        instance_name = "SSM_S3_IR_Extraction01"

        try:
            new_role = iam.create_role(
                RoleName=role_name, Path="/./", AssumeRolePolicyDocument=data
            )

            policy_ssm = iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
            )

            policy_s3 = iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn="arn:aws:iam::aws:policy/AmazonS3FullAccess",
            )
        except Exception as e:
            if "EntityAlreadyExists" in str(e):
                pass
        try:
            create_instance_profile = iam.create_instance_profile(
                InstanceProfileName=instance_name
            )
            attach_role = iam.add_role_to_instance_profile(
                RoleName=role_name, InstanceProfileName=instance_name
            )
        except Exception as e:
            if "EntityAlreadyExists" in str(e):
                create_instance_profile = iam.get_instance_profile(
                    InstanceProfileName=instance_name
                )

        profile_for_replace = {}
        profile_for_replace["Arn"] = create_instance_profile["InstanceProfile"]["Arn"]
        profile_for_replace["Name"] = create_instance_profile["InstanceProfile"][
            "InstanceProfileName"
        ]
        os.remove(ROLE_JSON)

        return profile_for_replace

    def associate_role(self, instanceid, instance_prof):
        ec2 = boto3.client("ec2")
        string = "" + instance_prof["Name"] + ""
        associate_prof = ec2.associate_iam_instance_profile(
            InstanceId=instanceid, IamInstanceProfile={"Name": string}
        )

    def extract_role_and_id(self):
        ec2 = boto3.client("ec2")
        list_instances_profiles = ec2.describe_iam_instance_profile_associations()
        old_profiles = []
        profile = {}
        prof = {}

        for instance in list_instances_profiles["IamInstanceProfileAssociations"]:
            profile["instanceID"] = instance["InstanceId"]
            prof["Arn"] = instance["IamInstanceProfile"]["Arn"]
            prof["Name"] = instance["IamInstanceProfile"]["Arn"].split("/")[1].strip()
            profile["profileARN"] = prof
            profile["AssociatedID"] = instance["AssociationId"]
            old_profiles.append(profile)
            profile = {}
            prof = {}

        return old_profiles

    def replace_role(self, iam_profile, associate_id):
        ec2 = boto3.client("ec2")
        new_profile = ec2.replace_iam_instance_profile_association(
            IamInstanceProfile=iam_profile, AssociationId=associate_id
        )

        return new_profile

    def extract_list_ssm_instances(self):
        ssm = boto3.client("ssm")
        ssm_instances = ssm.describe_instance_information()
        total_ssm_instances = []

        for instance in ssm_instances["InstanceInformationList"]:
            total_ssm_instances.append(instance["InstanceId"])

        return total_ssm_instances

    def extract_logs(self):
        ssm = boto3.client("ssm")
        list_of_logs = [
            "cat /var/log/syslog",
            "cat /var/log/messages",
            "cat /var/log/auth.log",
            "cat /var/log/secure",
            "cat /var/log/boot.log",
            "cat /var/log/dmesg",
            "cat /var/log/faillog",
            "cat /var/log/cron",
            "cat /var/log/kern.log",
        ]

        total_ssm_instances = self.extract_list_ssm_instances()
        send_command = ssm.send_command(
            InstanceIds=total_ssm_instances,
            DocumentName="AWS-RunShellScript",
            OutputS3BucketName=self.bucket,
            OutputS3KeyPrefix="ec2",
            Parameters={"commands": list_of_logs},
        )

    def switch_profiles(self, old_profiles, fields, IamInstanceProfile):
        for profile in old_profiles:
            if fields["InstanceId"] == profile["instanceID"]:
                self.replace_role(IamInstanceProfile, profile["AssociatedID"])

    def new_profiles_instances(self, profiles, instances, IamInstanceProfile):
        for instance in instances["Reservations"][0]:
            for fields in instance["Instances"]:
                if "IamInstanceProfile" in fields:
                    self.switch_profiles(profiles, fields, IamInstanceProfile)
                else:
                    self.associate_role(fields["InstanceId"], IamInstanceProfile)

    def back_to_normal(self, old_profiles, new_profiles):
        for old_profile in old_profiles:
            for new_profile in new_profiles:
                if old_profile["instanceID"] == new_profile["instanceID"]:
                    self.replace_role(
                        old_profile["profileARN"], new_profile["AssociatedID"]
                    )

    def get_logs_ec2(self):
        ec2_list = self.services["ec2"]

        response = try_except(EC2_CLIENT.describe_instances)
        response.pop("ResponseMetadata", None)
        instances = fix_json(response)

        if ec2_list["count"] == -1:
            if instances["Reservations"]:
                instances = instances["Reservations"][0]["Instances"]

                if len(instances) == 0:
                    self.display_progress(0, "ec2")
                    return

            else:
                self.display_progress(0, "ec2")
                return

        elif ec2_list["count"] == 0:
            self.display_progress(0, "ec2")
            return

        profile_for_replace = self.create_ssm_role()

        time.sleep(60)

        old_profiles = self.extract_role_and_id()
        self.new_profiles_instances(old_profiles, instances, profile_for_replace)

        time.sleep(60)

        self.extract_logs()
        new_profiles = self.extract_role_and_id()
        self.back_to_normal(old_profiles, new_profiles)
        self.display_progress(1, "ec2")

    def download_rds(self, nameDB, rds, logname):
        response = try_except(
            rds.download_db_log_file_portion,
            DBInstanceIdentifier=nameDB,
            LogFileName=logname,
            Marker="0",
        )

        return response.get("LogFileData", "")

    def get_logs_rds(self):
        rds_list = self.services["rds"]

        if rds_list["count"] == -1:
            response = try_except(RDS_CLIENT.describe_db_instances)
            response.pop("ResponseMetadata", None)
            response = fix_json(response)
            list_of_dbs = response.get("DBInstances", [])

            if len(list_of_dbs) == 0:
                self.display_progress(0, "rds")
                return

        elif rds_list["count"] == 0:
            self.display_progress(0, "rds")
            return
        else:
            list_of_dbs = rds_list["elements"]

        total_logs = []

        for db in list_of_dbs:
            total_logs.append(
                self.download_rds(
                    db["DBInstanceIdentifier"],
                    RDS_CLIENT,
                    "external/mysql-external.log",
                )
            )
            total_logs.append(
                self.download_rds(
                    db["DBInstanceIdentifier"], RDS_CLIENT, "error/mysql-error.log"
                )
            )

        self.display_progress(len(list_of_dbs), "rds")
        write_s3(
            self.bucket,
            LOGS_KEY + "rds/rds.json",
            json.dumps(total_logs, indent=4, default=str),
        )
        return

    def get_logs_route53(self):
        route53_list = self.services["route53"]

        if route53_list["count"] == -1:
            response = try_except(ROUTE53_CLIENT.list_hosted_zones)
            response.pop("ResponseMetadata", None)
            response = fix_json(response)
            hosted_zones = response.get("HostedZones", [])

            if hosted_zones:
                self.display_progress(0, "route53")
                return

        elif route53_list["count"] == 0:
            self.display_progress(0, "route53")
            return

        route53resolver = boto3.client("route53resolver")
        response = try_except(route53resolver.list_resolver_query_log_configs)
        resolver_log_configs = response.get("ResolverQueryLogConfigs", [])
        cnt = 0

        for bucket_location in resolver_log_configs:
            if "s3" in bucket_location["DestinationArn"]:
                bucket = bucket_location["DestinationArn"].split(":")[-1]
                src_bucket = bucket.split("/")[0]
                self.copy_s3_bucket(src_bucket, self.bucket, "route53")
                cnt += 1
        self.display_progress(cnt, "route53")

    def display_progress(self, count, name):
        if count != 0:
            print(
                "         \u2705 "
                + name.upper()
                + "\033[1m"
                + " - Logs extracted to S3 bucket "
                + "\033[0m"
            )
        else:
            print(
                "         \u274c " + name.upper() + "\033[1m" + " - No Logs" + "\033[0m"
            )