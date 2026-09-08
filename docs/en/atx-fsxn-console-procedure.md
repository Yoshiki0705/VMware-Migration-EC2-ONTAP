# Procedure: Setting FSx for ONTAP as the Target Storage in the MGN Console

**Purpose**: The console steps for specifying Amazon FSx for NetApp ONTAP as the replication target storage in AWS Transform MGN. Screenshots were captured against a live environment in ap-northeast-1 on 2026-09-04.

**Last Updated**: 2026-09-04
**Applies to**: AWS Transform MGN (formerly AWS Application Migration Service), FSx for ONTAP target GA (2026-08-30)

> **Scope**: this procedure covers configuration input only. It does not cover running replication, cutover, or Finalize.
>
> Migration after configuration proceeds in five stages (continuous replication, testing, cutover, rollback, Finalize), and **the irreversible point is Finalize, not cutover**. Testing uses FlexClone, so it can be repeated any number of times without stopping replication. **And Finalize is not cleanup — it is the step where physical capacity peaks, with the split temporarily needing one extra copy of the migrated data** (12.10). For that mechanism and the full constraint picture, see sections 8 and 9 of the [ATX FSx for ONTAP GA verification report](./atx-fsxn-ga-verification.md), particularly 9.7. The primary source is the [AWS Storage Blog](https://aws.amazon.com/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/).

---

## 1. Handling of Screenshots

The images in this procedure live in `verification/screenshots/masked/`. Account IDs, IAM user names, resource IDs, and internal organizational names were replaced at capture time.

| Category | Location | git |
|---|---|---|
| Raw images | `verification/screenshots/raw/` | Excluded by `.gitignore`. Never committed |
| Redacted | `verification/screenshots/masked/` | Committed |

Two redaction methods were used, and they carry different strengths of guarantee.

| Method | Applied to | Guarantee |
|---|---|---|
| DOM replacement, then capture | Reproducible screens | The string is absent from the DOM at capture time, so it cannot be present in the pixels |
| Image replacement (`tools/redact_screenshot.py`) | Transient screens that cannot be recaptured | Blacks out OCR word-level bounding boxes, plus unconditionally paints over the header strip |

Verification is done with OCR, checking in pairs that **a string readable in the raw image is no longer readable after redaction**. Without that control, "OCR cannot read it" gets mistaken for "the redaction worked". Dark-theme screens defeat OCR on body text, so no control is possible for them, and the guarantee there rests on DOM replacement.

---

## 2. Prerequisites

| # | Condition | How to check |
|---|---|---|
| 1 | An FSx for ONTAP file system is `AVAILABLE` | `aws fsx describe-file-systems` |
| 2 | An SVM is `CREATED` | `aws fsx describe-storage-virtual-machines` |
| 3 | MGN and FSx for ONTAP are in the same account and Region | — |
| 4 | The ONTAP management endpoint is reachable from inside the VPC | `curl -k https://<mgmt-ip>/api/cluster` returns 401 from a host in the VPC |
| 5 | A client certificate is stored in Secrets Manager | See section 5 |

Steps through section 4 work without condition 5. Saving the configuration requires it.

---

## 3. Initializing the Service

When MGN is not initialized, opening `Settings → Replication template` redirects to the setup screen.

![MGN service initialization screen](../../verification/screenshots/masked/05-mgn-setup-service-init.png)

The explanatory text states that continuing authorizes AWS Transform MGN to create all the IAM roles needed for data replication and for launching migrated servers. Choose `Set up service`.

> **The CLI can fail here**: environments have been observed where `aws mgn initialize-service` fails reproducibly with `ValidationException: Failed to create SLR or instance profiles` (`reason: OTHER`), while console initialization succeeds. When the CLI fails it leaves behind the service-linked role plus **four instance profiles with no role attached**. Deleting those empty profiles before initializing from the console makes the resulting state easier to read. See [verification report 5.4](./atx-fsxn-ga-verification.md).

Once initialization completes, a "default template created" notification appears.

![Initialization complete](../../verification/screenshots/masked/06-mgn-init-success.png)

Check the roles that were created.

```bash
aws iam list-roles \
  --query "Roles[?contains(RoleName,'ApplicationMigration')].RoleName" \
  --output json
```

Confirm that the two roles added for FSx for ONTAP support are present.

| Role | Attached managed policy | Purpose |
|---|---|---|
| `AWSApplicationMigrationFsxProxyRole` | `AWSApplicationMigrationFSxProxyPolicy` | Path to reach FSx |
| `AWSApplicationMigrationFsxProxyLinkRole` | `AWSApplicationMigrationFSxProxyVPCPolicy` | The VPC-side connection (PrivateLink) |

Without these two roles, selecting FSx for ONTAP as the target will not work. In environments initialized before FSx for ONTAP support existed, run `Reinitialize Service Permissions` on the replication template page.

---

## 4. Selecting the Target Storage

Open `Settings → Replication template`. The initial `Default Storage Provider` is `EBS`.

![Replication template with the EBS default](../../verification/screenshots/masked/07-mgn-replication-template-ebs.png)

Choose `Edit` and scroll to the `Storage configuration` section. There are two tiles.

| Tile | On-screen description |
|---|---|
| EBS (Elastic Block Storage) | High-performance block storage attached directly to EC2 instances |
| Amazon FSx for NetApp ONTAP | For workloads requiring shared storage or specialized file system features |

Selecting `Amazon FSx for NetApp ONTAP` changes three things on screen.

![After selecting FSx for ONTAP](../../verification/screenshots/masked/09-mgn-fsxn-selected-config.png)

| Change | Detail |
|---|---|
| A note appears | "Data disks will be migrated to FSx for ONTAP. Boot disk is always migrated to EBS as required by Amazon EC2." |
| A label changes | "EBS volume type (for replicating disks over 500 GiB)" becomes "EBS volume type (for boot disk)" |
| A section appears | "Amazon FSx for NetApp ONTAP configuration" (SVM ID and Secret ARN) |

The boot-disk-on-EBS constraint is not only documented; it is **stated on the screen itself**.

### Selecting the SVM

The `Storage Virtual Machine (SVM) ID` dropdown enumerates SVMs across every FSx for ONTAP file system in the Region. Each entry shows SVM name, SVM ID, and the parent file system ID with its name.

![SVM dropdown](../../verification/screenshots/masked/10-mgn-svm-dropdown.png)

There is no filtering by AD-join status. AD-joined SVMs appear in the same list, so they have to be distinguished at selection time.

### Selecting the Secret ARN

The `FSx Storage Secret ARN` dropdown **enumerates every Secrets Manager secret in the Region. There is no filtering.**

![Secret ARN dropdown](../../verification/screenshots/masked/11-mgn-secret-arn-empty.png)

In testing, all 23 secrets in the Region were offered. Only one carried the `AWSApplicationMigrationServiceManaged` tag, and **untagged secrets appear in the same list**.

> **A verification note**: this list was initially recorded as "filtered to tagged secrets only", which was wrong. The list appeared empty before a tagged secret existed because it was observed before the dropdown had loaded, not because of any filter. **Do not infer a filter rule from an empty render.**

Consequently the UI **permits selecting a secret with the wrong tag or the wrong content format**. The tag (`AWSApplicationMigrationServiceManaged` = `True`) and the key names (`cert` / `key`) are conditions the official procedure requires for MGN to use the secret, but they are not enforced at selection time. A mistake does not surface until replication starts.

Check it yourself before selecting.

```bash
aws secretsmanager list-secrets --region <region> \
  --query 'SecretList[?Tags[?Key==`AWSApplicationMigrationServiceManaged`]].Name' \
  --output json
```

---

## 5. Required Fields and Validation Behaviour

With `Amazon FSx for NetApp ONTAP` selected, choosing `Save template` while the fields are blank is rejected on three required fields.

![Required-field validation](../../verification/screenshots/masked/12-mgn-fsxn-required-field-validation.png)

| Required field | On-screen message |
|---|---|
| Storage Virtual Machine (SVM) ID | States that the field is required when `Default Storage Provider` is `Amazon FSx for NetApp ONTAP` |
| FSx Storage Secret ARN | Required on the same condition |
| Additional security groups | Required on the same condition |

**That "Additional security groups" becomes required is not evident from the procedure text in the MGN User Guide.** It only surfaces in the console, so an iSCSI security group has to be prepared in advance.

The on-screen text gives the reason: "When using Amazon FSx as the default storage provider, the security group must also allow communication with Amazon FSx." The default MGN security group opens only inbound 1500, which does not cover FSx traffic (3260 / 443), so an additional group is demanded.

> **Validation is weaker via the API than in the console**: the API (`update-replication-configuration-template`) **accepts and persists** `storageType=FSX_ONTAP` with a non-existent secret ARN. The SVM ID is checked for existence by the API too, but the secret ARN is not. So **when configured through the API, a mistake does not surface until replication starts**. If you configure this through IaC or the CLI, validate the existence and contents of the secret ARN yourself. See [verification report 4.4](./atx-fsxn-ga-verification.md).

---

## 6. Creating the Certificate and the Secret

### 6.1 Reaching the management endpoint

The management endpoint is reachable only from inside the VPC. Passing credentials to a bastion leaves them in plaintext in SSM command history, so on a shared account the approach taken here is an **SSM port-forward tunnel, with the credentials used from the local machine**.

```bash
aws ssm start-session --target <instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<mgmt-ip>"],"portNumber":["443"],"localPortNumber":["8443"]}'
```

Prerequisites are session-manager-plugin and SSM agent 3.1.1374.0 or later. This works across a VPC peering connection (measured).

### 6.2 Generating the certificate

The private key must be PKCS#8. `openssl req` produces PKCS#1 by default, so convert it.

```bash
CN=mgn-fsx-client
openssl req -x509 -newkey rsa:2048 -nodes -keyout raw.key -out client.crt \
  -days 730 -subj "/CN=$CN"
openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt -in raw.key -out client.key
rm -f raw.key
head -1 client.key   # must read -----BEGIN PRIVATE KEY-----
```

### 6.3 Installing it on ONTAP

Using the REST API keeps everything over the tunnel with no SSH.

```bash
python3 -c 'import json,pathlib; print(json.dumps({"type":"client_ca","public_certificate":pathlib.Path("client.crt").read_text()}))' > body.json
curl -sS -k -u "$U:$P" -X POST -H 'Content-Type: application/json' \
  --data @body.json https://127.0.0.1:8443/api/security/certificates

curl -sS -k -u "$U:$P" -X POST -H 'Content-Type: application/json' \
  -d '{"name":"mgn-fsx-client","owner":{"name":"<FsxId...>"},
       "applications":[{"application":"http","authentication_methods":["certificate"]}],
       "role":{"name":"fsxadmin"}}' \
  https://127.0.0.1:8443/api/security/accounts
```

The login name must match the certificate's CN. To do this from the CLI instead, use `security certificate install` and `security login create` per the official procedure.

**Verify with a negative control.** Without confirming both a 200 with the certificate and a 401 without it, you cannot tell whether the certificate is doing anything or the request would have succeeded anyway.

```bash
curl -sS -k --cert client.crt --key client.key https://127.0.0.1:8443/api/cluster
curl -s -k -o /dev/null -w '%{http_code}\n' https://127.0.0.1:8443/api/cluster   # must be 401
```

> **A note on scope**: `vserver_name` in the official steps refers to the **admin vserver**, named in file-system-ID form (`FsxId...`), not a data SVM. On a shared file system this is therefore a **cluster-scope addition of an authentication path**. It only adds; existing authentication is unchanged. No privilege reaches anyone without the private key.
>
> **Teardown is not fully reversible (measured)**: `fsxadmin` can delete the `security login`, but **deleting the client-ca certificate returns 403 `not authorized for that command` for `fsxadmin`** (rejected via both `DELETE /api/security/certificates/{uuid}` and the private CLI passthrough; measured on ONTAP 9.18.1P3D1). Deleting the login is enough to revoke access - certificate authentication then fails with 403 - but the certificate itself remains as an inert artifact. If leaving a permanent artifact on a shared file system is not acceptable, agree on this beforehand.
>
> A created SVM does get its own management LIF, so an SVM-scoped `security login` might suffice, but that is **untested** (U14 in the verification report). Departing from the official procedure makes failures harder to triage.

Note that FSx pre-installs two cluster-scope client-ca certificates (`FSxCAforONTAP-1in<region>` and `AmazonFSxRootCA1for<region>`). A certificate you install coexists with those.

### 6.4 Storing it in Secrets Manager

| Condition | Detail |
|---|---|
| Key names | Exactly `cert` and `key`. `certificate` / `private_key` are not accepted |
| Must not include | A `username` field |
| Private key format | PKCS#8 |
| Tag | `AWSApplicationMigrationServiceManaged` = `True` |

```bash
aws secretsmanager create-secret --region <region> \
  --name mgn/fsx-ontap/client-certificate \
  --secret-string file://secret.json \
  --tags Key=AWSApplicationMigrationServiceManaged,Value=True
```

Delete the local private key afterwards. Secrets Manager becomes the only copy.

---

## 7. Completing the Save

With the three required fields filled in, the template saves.

![Required fields satisfied](../../verification/screenshots/masked/13-mgn-fsxn-fields-populated.png)

After saving, `Default Storage Provider` reads `Amazon FSx for NetApp ONTAP`, with the SVM ID and Secret ARN shown.

![Template after saving](../../verification/screenshots/masked/14-mgn-template-saved-fsxn.png)

**Do not judge from the screen alone.** Read the value back through the API.

```bash
aws mgn describe-replication-configuration-templates --region <region> \
  --query 'items[].{id:replicationConfigurationTemplateID,storage:storageConfiguration}' \
  --output json
```

Confirm `storageType` is `FSX_ONTAP` and that `fsxOntapConfiguration` carries the SVM ID and Secret ARN. Resolve both to names with `describe-storage-virtual-machines` and `describe-secret` to confirm they point at what you intended.

## 8. What This Procedure Confirmed, and What It Did Not

| Item | Status |
|---|---|
| Service initialization from the console | Measured, succeeded |
| Creation of the two FSx-specific IAM roles | Measured, confirmed |
| Existence of the target storage selection UI | Measured, confirmed |
| On-screen statement that the boot disk stays on EBS | Measured, confirmed |
| SVM enumeration | Measured, confirmed |
| Validation of the three required fields | Measured, confirmed |
| Certificate authentication (with a negative control) | Measured, succeeded (200 with the certificate, 401 without) |
| **Saving the template** | **Measured, succeeded** (confirmed by API read-back) |
| Anything from replication onward | **Not done** |

For the prerequisites to go beyond replication, see sections 8 and 9 of the verification report. Automatic backups are a file-system setting, so disabling them extends to every volume on the file system (retention=0 also deletes the existing automatic backups). ARP is controllable per volume and as an SVM default, so it can be isolated with a dedicated SVM.

---

## Reference Links

- [FSx for ONTAP configuration (MGN User Guide)](https://docs.aws.amazon.com/mgn/latest/ug/fsx-ontap.html)
- [What's New: AWS Transform FSx for NetApp ONTAP support GA](https://aws.amazon.com/about-aws/whats-new/2026/09/aws-transform-fsx-netapp-ontap-support/)
- [Migrate VMware Storage to Amazon FSx for NetApp ONTAP using AWS Transform (AWS Storage Blog)](https://aws.amazon.com/blogs/storage/migrate-vmware-storage-to-amazon-fsx-for-netapp-ontap-using-aws-transform/) — the five migration stages, the role of FlexClone, and best practices
- [AWS Transform Change log](https://docs.aws.amazon.com/transform/latest/userguide/change-log.html)
- [ATX FSx for ONTAP GA verification report (this repository)](./atx-fsxn-ga-verification.md)
- [Migration method comparison (this repository)](./migration-method-comparison.md)
- [Maximum number of SVMs per file system, which scales with throughput capacity](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-svms.html)
- [Automatic backups are a file system setting](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-backups.html)
- [Enabling ARP, per volume and as an SVM default](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/enable-ARP.html)

---

*This procedure is based on live screens captured in ap-northeast-1 on 2026-09-04. The UI is subject to change; where it differs, the official documentation takes precedence.*
