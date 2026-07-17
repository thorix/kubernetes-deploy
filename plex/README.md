# Plex Media Server

Plex Media Server organizes your personal media collection (movies, TV shows, music, photos) and streams it to all your devices.

## Overview

This deployment installs Plex Media Server on Kubernetes with:

1. **SMB Volume Integration** - Mount media from network shares (NAS/Windows)
2. **Vault Secret Management** - Secure storage of Plex claim tokens and SMB credentials
3. **Hardware Transcoding** - Memory-backed transcode directory for performance
4. **Persistent Configuration** - Config stored on host path for metadata/database
5. **Network Discovery** - GDM, DLNA, and Bonjour support for device discovery

## Architecture

```
┌─────────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  SMB Server         │     │  Longhorn       │     │  Cloudflare     │
│  (nas.lan)      │     │  (Storage)      │     │  Tunnel         │
└──────────┬──────────┘     └────────┬────────┘     └────────┬────────┘
           │ SMB/CIFS                │                       │
           │                         │                       │
┌──────────▼──────────┐     ┌────────▼────────┐     ┌────────▼────────┐
│  CSI Driver (SMB)   │     │  CSI (Longhorn) │     │  Vault Server   │
│  (Media + OTA PVs)  │     │  (Config PVC)   │     │  (Secrets)      │
└──────────┬──────────┘     └────────┬────────┘     └────────┬────────┘
           │                         │                       │
           │                         │                       │
┌──────────▼─────────────────────────▼───────────────────────▼──────────┐
│  Plex StatefulSet                                                      │
│  - Config: /config (Longhorn 100Gi RWO)                                │
│  - Media: /data/media (SMB read-only, 10Ti)                            │
│  - OTA Recordings: /data/overTheAir (SMB read-write, 1Ti)              │
│  - Transcode: /transcode (tmpfs memory 8Gi)                            │
└────────────────────────────────────────────────────────────────────────┘
```

**Security Design:**
- **Media library**: Read-only SMB mount (prevents accidental modification/deletion)
- **Writable data**: Longhorn volumes (better performance, snapshots, backups)
- **Transcode**: Memory-backed for maximum performance

## Prerequisites

### 1. Namespace Configuration (Pod Security Standards)

**IMPORTANT**: Plex is configured with the **privileged** Pod Security Standard for flexibility and compatibility.

**Note:** With the current configuration (Longhorn PVCs, emptyDir memory volumes), Plex *could* run under **baseline** Pod Security. However, privileged is configured to allow for future requirements or troubleshooting without namespace reconfiguration.

The `plex` namespace must be configured in the `cluster-infrastructure` deployment with privileged Pod Security labels.

**Verification:**
```bash
# Check namespace has correct labels
kubectl get namespace plex -o yaml | grep pod-security

# Expected output:
# pod-security.kubernetes.io/enforce: privileged
# pod-security.kubernetes.io/audit: privileged
# pod-security.kubernetes.io/warn: privileged
```

**Configuration:**

This is managed in `cluster-infrastructure/values.prod.yaml`:
```yaml
namespaces:
  enabled: true
  configs:
    - name: plex
      labels:
        pod-security.kubernetes.io/enforce: privileged
        pod-security.kubernetes.io/audit: privileged
        pod-security.kubernetes.io/warn: privileged
```

If the namespace doesn't have these labels, the StatefulSet will fail with:
```
pods "plex-0" is forbidden: violates PodSecurity "baseline:latest": hostPath volumes
```

**For Future Deployments:**

When creating new deployments that require special permissions:

1. **Identify Pod Security Requirements:**
   - **privileged**: Required for hostPath, privileged containers, host networking
   - **baseline**: Default for most applications, prevents privilege escalation
   - **restricted**: Most restrictive, enforces pod hardening best practices

2. **Add Namespace to cluster-infrastructure:**
   Edit `cluster-infrastructure/values.prod.yaml` and add your namespace under `namespaces.configs`

3. **Document in README Prerequisites:**
   Always document the Pod Security requirement and reasoning

4. **Common Scenarios:**
   - CSI drivers → privileged (host volume mounting)
   - Workloads with hostPath or host networking → privileged
   - Standard web apps → baseline (default)
   - High-security apps → restricted (maximum hardening)

### 2. SMB CSI Driver

The SMB CSI Driver must be installed first:

```bash
cd ../csi-driver-smb
helm dependency update
helm upgrade --install \
  --create-namespace \
  --namespace csi-driver-smb \
  --values values.yaml \
  --values values.prod.yaml \
  csi-driver-smb .
```

Verify the driver is running:

```bash
kubectl get pods -n csi-driver-smb
kubectl get csidrivers smb.csi.k8s.io
```

### 3. Vault Secrets Operator

VSO must be installed and configured. See the standard deployment pattern in cloudflare-tunnel/README.md.

### 4. Longhorn Storage

Longhorn must be installed and configured as the storage provider for persistent volumes.

**Verification:**
```bash
# Check Longhorn is available
kubectl get storageclass longhorn

# Check Longhorn pods are running
kubectl get pods -n longhorn-system
```

**Storage Requirements:**
- **Config volume**: 100Gi (metadata, database, logs, cache)
- **OTA Recordings**: 1Ti (over-the-air TV recordings)

Longhorn provides:
- Automatic replication across nodes
- Snapshots and backups
- Better performance than SMB for database operations

### 5. SMB Server Access

- **Server**: nas.lan (or your SMB server)
- **Share**: `/media` - Main media library (mounted read-only for security)
- **Credentials**: Stored in Vault at `kv/smb/nas/server`

**Important:** The media library is mounted **read-only** to prevent accidental modification or deletion of media files. All writable data (Plex database, recordings) uses Longhorn storage.

## Required Vault Configuration

### 1. Store Plex Claim Token in Vault

Get a claim token from https://www.plex.tv/claim/ (valid for 4 minutes):

```bash
# Store the claim token
vault kv put kv/plex/claim PLEX_CLAIM="claim-xxxxxxxxxxxxxxxxxxxx"

# Verify
vault kv get kv/plex/claim
```

**Important**: The claim token is only needed for initial setup. After Plex is claimed, it's no longer required but the secret should remain for future re-deployments.

### 2. Store SMB Credentials in Vault

```bash
# Store SMB username and password
vault kv put kv/smb/nas/server \
  username="your-smb-username" \
  password="your-smb-password"

# Verify
vault kv get kv/smb/nas/server
```

**Important**: The secret keys MUST be named `username` and `password` exactly as the SMB CSI driver expects these field names.

### 3. Vault Policy and Auth Role (Automatic)

The Vault policy and Kubernetes auth role are **automatically created** by the vault-config-operator when this chart is deployed. The chart includes:

- `vault-policy.yaml` - Creates the `plex` policy in Vault with read access to required secrets
- `vault-auth-role.yaml` - Creates the `plex` Kubernetes auth role bound to the service account

**Prerequisites**: The vault-config-operator must be installed and configured. See `vault-config-operator/README.md` for setup instructions.

**Verification** (after deployment):

```bash
# Check the Policy CR status
kubectl describe policies.redhatcop.redhat.io plex -n plex

# Check the KubernetesAuthEngineRole CR status
kubectl describe kubernetesauthengineroles.redhatcop.redhat.io plex -n plex

# Verify in Vault
vault policy read plex
vault read auth/kubernetes/role/plex
```

## Deployment

### Manual Deployment

```bash
# Update Helm dependencies (if any)
helm dependency update

# Deploy to production
helm upgrade --install \
  --create-namespace \
  --namespace plex \
  --values values.yaml \
  --values values.prod.yaml \
  plex .
```

### ArgoCD Deployment

This deployment is automatically discovered by the ApplicationSet. Commit the files and push:

```bash
git add plex/
git commit -m "Add Plex deployment"
git push
```

The ApplicationSet will create an Application for this deployment automatically.

## Verification

### Check Pod Status

```bash
kubectl get pods -n plex
kubectl logs -n plex plex-0
```

### Check Secrets

Verify that VSO created the secrets:

```bash
# Check SMB credentials
kubectl get secret -n plex smbcreds
kubectl get secret -n plex smbcreds -o jsonpath='{.data.username}' | base64 -d
echo ""

# Check Plex secrets
kubectl get secret -n plex plex-secrets
kubectl get secret -n plex plex-secrets -o jsonpath='{.data.PLEX_CLAIM}' | base64 -d
echo ""
```

### Check Volumes

```bash
# Check PVs and PVCs
kubectl get pv | grep plex
kubectl get pvc -n plex

# Check volume mounts in pod
kubectl exec -n plex plex-0 -- df -h | grep -E '/data|/config|/transcode'
```

### Access Plex

**Internal Access:**
1. **Via NodePort**: http://NODE_IP:32400/web
2. **Via Tailscale**: http://plex.tailscale-network/web (trusted devices on Tailscale network)

**External Access (Cloudflare Tunnel):**
3. **Via Cloudflare**: https://pl2090631.lan/web

The Cloudflare Tunnel provides secure external access with:
- **WAF Protection**: Geo-blocking restricts access to USA IPs only
- **No Port Forwarding**: Traffic routes through Cloudflare's edge network
- **Cache Bypass**: Streaming content is not cached
- **Plex Authentication**: Plex handles user authentication (no Cloudflare Access)

Tunnel configuration is managed in `~/git/YOUR_ORG/cloud-deploy/cloudflare-tunnel/`

## Configuration

### Update Plex Version

Check for updates:

```bash
./current-version.sh
```

Update to a new version:

```bash
# Update values.yaml with new image tag
sed -i 's|image: plexinc/pms-docker:.*|image: plexinc/pms-docker:NEW_VERSION|' values.yaml

# Commit and push
git add values.yaml
git commit -m "Update Plex to NEW_VERSION"
git push
```

### Modify Media Sources

To add/change SMB shares:

1. Update `values.yaml` smb section
2. Update PersistentVolume sources in templates
3. Update Vault policy if using different paths
4. Commit and push changes

### Resource Limits

Default resources (values.yaml):
- CPU: 500m request, 4000m limit
- Memory: 1Gi request, 4Gi limit
- Transcode: 4Gi memory

Production resources (values.prod.yaml):
- CPU: 1000m request, 8000m limit
- Memory: 2Gi request, 8Gi limit
- Transcode: 8Gi memory

Adjust based on your usage and hardware transcoding needs.

### Storage Volumes

Plex uses a hybrid storage strategy for optimal performance and security:

**Longhorn Volumes (Dynamic, Writable):**
- **Config volume** (`/config`): 100Gi
  - Plex metadata, database, cache
  - Automatically backed up with Longhorn snapshots
  - Fast local storage for database queries

**SMB Volumes (Static, NAS Storage):**
- **Media library** (`/data/media`): 10Ti
  - Existing media collection on NAS
  - **Read-only** for security (prevents accidental deletion)
  - Shared across multiple services if needed

- **OTA Recordings** (`/data/overTheAir`): 1Ti
  - Over-the-air TV recordings
  - **Read-write** for DVR functionality
  - Stored on NAS for centralized storage

**Memory Volume (Ephemeral):**
- **Transcode** (`/transcode`): 8Gi
  - Temporary transcoding storage
  - Memory-backed for maximum I/O performance
  - Cleared on pod restart

**Storage Configuration:**

Default (values.yaml):
```yaml
plex:
  storage:
    configSize: 50Gi
```

Production (values.prod.yaml):
```yaml
plex:
  storage:
    configSize: 100Gi
```

**Expanding Storage:**

Longhorn config volume can be expanded without data loss:
```bash
# Edit the PVC to request more storage
kubectl edit pvc -n plex config-plex-0

# Change spec.resources.requests.storage to new size
# Longhorn will automatically expand the volume
```

## Troubleshooting

### Pod fails to start with "permission denied" on SMB mount

**Check:**

1. Verify SMB credentials in Vault:
   ```bash
   vault kv get kv/smb/nas/server
   ```

2. Verify the VaultStaticSecret created the Kubernetes secret:
   ```bash
   kubectl get secret -n plex smbcreds
   ```

3. Check VSO logs:
   ```bash
   kubectl logs -n vault-secrets-operator-system deployment/vault-secrets-operator-controller-manager
   ```

4. Test SMB connectivity from a debug pod:
   ```bash
   kubectl run -n plex -it --rm smbtest --image=alpine --restart=Never -- sh
   apk add samba-client
   smbclient //nas.lan/media -U username%password
   ```

### Plex shows "Unclaimed server"

**Cause**: The claim token expired or wasn't provided.

**Fix:**

1. Get a new claim token from https://www.plex.tv/claim/
2. Update Vault:
   ```bash
   vault kv patch kv/plex/claim PLEX_CLAIM="claim-xxxxxxxxxxxxxxxxxxxx"
   ```
3. Restart the pod:
   ```bash
   kubectl rollout restart statefulset -n plex plex
   ```
4. Access Plex web UI within 4 minutes and sign in

### Media library not showing files

**Check:**

1. Verify PV is bound:
   ```bash
   kubectl get pv plex-media
   kubectl get pvc -n plex plex-media
   ```

2. Check mount inside pod:
   ```bash
   kubectl exec -n plex plex-0 -- ls -la /data/media
   ```

3. Verify SMB mount options (uid/gid):
   ```bash
   kubectl exec -n plex plex-0 -- stat /data/media
   ```

### Transcoding fails or is slow

**Check:**

1. Verify transcode directory has memory backing:
   ```bash
   kubectl exec -n plex plex-0 -- df -h /transcode
   # Should show tmpfs with memory
   ```

2. Check memory limits aren't too low:
   ```bash
   kubectl describe pod -n plex plex-0 | grep -A 5 Limits
   ```

3. Increase transcodeMemory in values if needed

### Configuration changes not persisting

**Cause**: Config volume not properly mounted or permissions wrong.

**Check:**

1. Verify the config PVC is bound:
   ```bash
   kubectl get pvc -n plex config-plex-0
   # Should show STATUS: Bound
   ```

2. Verify Longhorn volume health:
   ```bash
   # Check the Longhorn volume
   kubectl get volumes -n longhorn-system | grep plex

   # Or check in Longhorn UI
   # The volume should be "healthy" and "attached"
   ```

3. Check pod can write to config:
   ```bash
   kubectl exec -n plex plex-0 -- touch /config/test-write
   kubectl exec -n plex plex-0 -- ls -la /config/test-write
   # Should show file owned by uid 1000
   ```

4. Verify volume is mounted:
   ```bash
   kubectl exec -n plex plex-0 -- df -h /config
   # Should show Longhorn volume mounted
   ```

## Standard Vault Integration Pattern

This deployment follows the standard Vault Secrets Operator pattern:

```
VaultConnection → VaultAuth → VaultStaticSecret → Kubernetes Secret → Pod
```

**Components:**

1. **VaultConnection**: Defines Vault server URL (created by VSO installation)
2. **VaultAuth**: Kubernetes auth method (created by VSO installation)
3. **VaultStaticSecret**: Fetches specific secrets from Vault paths
4. **Kubernetes Secret**: Auto-created and managed by VSO
5. **Pod**: Consumes the secret via envFrom or volumeMounts

**Required for each deployment:**

- Vault KV secrets stored at defined paths
- Vault policy granting read access to those paths
- Kubernetes auth role binding service account to policy

**Troubleshooting Vault Issues:**

See cloudflare-tunnel/README.md for comprehensive Vault troubleshooting steps.

## Security Considerations

- **Claim Token**: Only needed for initial setup, expires after 4 minutes
- **SMB Credentials**: Stored in Vault, never in git or plain Kubernetes secrets
- **Read-Only Media**: Media library mounted read-only to prevent accidental modifications
- **Host Path Security**: Config directory uses specific UID/GID (1000) to prevent privilege escalation
- **Memory Transcode**: Transcode uses memory (tmpfs) to prevent disk wear and improve performance

## Network Ports

Plex uses multiple ports for different protocols:

- **32400**: Main Plex web interface and streaming (TCP)
- **32469**: DLNA server (TCP)
- **1900**: Bonjour/UPnP (UDP)
- **3005**: Plex Companion (TCP)
- **8324**: Roku via Plex Companion (TCP)
- **32410-32414**: GDM network discovery (UDP)

All ports are exposed via NodePort service with tailscale annotations for external access.

## References

- [Plex Media Server Documentation](https://support.plex.tv/articles/)
- [Plex Docker Image](https://hub.docker.com/r/plexinc/pms-docker)
- [SMB CSI Driver](https://github.com/kubernetes-csi/csi-driver-smb)
- [Vault Secrets Operator](https://developer.hashicorp.com/vault/docs/platform/k8s/vso)
