# Self-Hosted GitHub Actions Runners for Google Cloud

## Welcome 👋!

This tutorial guides you through deploying the self-hosted GitHub Actions Runners using **Google Cloud Shell**.

**Prerequisites**: A GCP project with billing enabled. The **Owner role** is the easiest option for this tutorial. If the Owner role is not possible, see [gcp/README.md](https://github.com/Cyclenerd/google-cloud-github-runner/blob/master/gcp/README.md) for the specific roles required.

<walkthrough-tutorial-duration duration="10"></walkthrough-tutorial-duration>

Click the **Start** button to move to the next step.

## Step 1: Project Setup

Select or create a project:

<walkthrough-project-setup billing=true></walkthrough-project-setup>

Enable the required APIs:

<walkthrough-enable-apis apis="artifactregistry.googleapis.com,cloudbuild.googleapis.com,cloudresourcemanager.googleapis.com,compute.googleapis.com,iam.googleapis.com,logging.googleapis.com,orgpolicy.googleapis.com,run.googleapis.com,storage.googleapis.com,secretmanager.googleapis.com"></walkthrough-enable-apis>

## Step 2: Configure Environment

Set Google Cloud project ID. Replace with your current Google Cloud project ID:

```bash
export GOOGLE_CLOUD_PROJECT="<walkthrough-project-id/>"
```

Configure gcloud to use this project:

```bash
gcloud config set project "$GOOGLE_CLOUD_PROJECT"
gcloud auth application-default set-quota-project "$GOOGLE_CLOUD_PROJECT"
```

## Step 3: Verify Organization Policies

**Crucial Step:** If you are deploying within an organization (e.g., a company account), certain policies might block public access to Cloud Run.

Enable the required service API:

```bash
gcloud services enable orgpolicy.googleapis.com --project="$GOOGLE_CLOUD_PROJECT" --quiet
```

Check Ingress (Should allow 'all'):

```bash
gcloud org-policies describe "run.allowedIngress" --effective --project="$GOOGLE_CLOUD_PROJECT" --quiet
```

Check Domain Sharing (Should 'allowAll'):

```bash
gcloud org-policies describe "iam.allowedPolicyMemberDomains" --effective --project="$GOOGLE_CLOUD_PROJECT" --quiet
```

If these are restrictive, you may need to ask your Organization Admin to adjust them or use a project outside the organization. See [gcp/README.md](https://github.com/Cyclenerd/google-cloud-github-runner/blob/master/gcp/README.md) for policy details.

## Step 4: Deploy with Terraform

The `gcp` directory contains the Terraform configuration.

Navigate to the `gcp` directory:

```bash
cd gcp
```

Create a `terraform.tfvars` file with your configuration.

Google Cloud project ID:

```bash
printf 'project_id = "%s"\n' "$GOOGLE_CLOUD_PROJECT" > terraform.tfvars
```

(Optional) Google Cloud region:

```bash
echo "region = \"us-central1\"" >> terraform.tfvars
```

(Optional) Google Cloud zone:

```bash
echo "zone = \"b\"" >> terraform.tfvars
```

For more details, see [gcp/README.md](https://github.com/Cyclenerd/google-cloud-github-runner/blob/master/gcp/README.md).
You find there a list of all variables and their default values.

Initialize Terraform:

```bash
terraform init
```

Apply the configuration:

```bash
terraform apply
```

* Review the plan when prompted.
* Type `yes` and press Enter to confirm.

## Step 5: Complete Setup

Once Terraform completes successfully, it will output a `service_url`.

1.  Copy the `service_url` (e.g., `https://google-cloud-github-runner-xyz-uc.a.run.app`).
2.  Open your browser and navigate to `service_url`.
    
    **Authentication Required:** You will be prompted for HTTP Basic Authentication credentials:
    - **Username:** `cloud`
    - **Password:** Your Google Cloud Project ID `<walkthrough-project-id/>` (the value you set in `GOOGLE_CLOUD_PROJECT`)
3.  Click **Setup GitHub App**, then install it on your target Organization or Repository.

## Step 6: Update Workflows

Configure your GitHub Actions CI/CD to use the runners. The `runs-on` key **must match** the name of the GCE Instance Template (e.g., `gcp-ubuntu-latest` or `gcp-ubuntu-24-04-8core-arm`).

```yaml
jobs:
  test:
    runs-on: gcp-ubuntu-latest  # Must match GCE Template Name
    steps:
      - run: echo "Hello from Google Cloud!"
```

## Optional: Migrate Terraform State to GCS

By default, Terraform stores state locally.
It's highly recommended to migrate this state to a remote **Google Cloud Storage (GCS)** backend.

Copy `providers.tf.gcs` to `providers.tf` (configured for GCS backend):

```bash
cp providers.tf.gcs providers.tf
```

Run `terraform init -migrate-state` to copy your local state to the bucket:

```bash
terraform init -migrate-state
```

## Done 🎉

<walkthrough-conclusion-trophy></walkthrough-conclusion-trophy>

You can now use the self-hosted GitHub Actions Runners on Google Cloud.
