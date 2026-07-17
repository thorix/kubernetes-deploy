# SMB CSI Driver

SMB CSI (Container Storage Interface) Driver for Kubernetes enables mounting SMB/CIFS network shares as persistent volumes.

## Overview

This deployment installs the SMB CSI Driver using the official Kubernetes CSI Helm chart. The driver enables:

1. **Mount SMB shares** - Connect to Windows/Samba file servers
2. **Dynamic provisioning** - Create PVCs backed by SMB shares
3. **Static provisioning** - Use pre-existing SMB shares
4. **Read-only mounts** - Mount shares in read-only mode for media libraries

## Use Cases

- **Media libraries**: Mount shared media storage for Plex, Jellyfin, etc.
- **Shared storage**: Access Windows file shares from containers
- **Legacy storage**: Connect to existing SMB/CIFS infrastructure
- **Network-attached storage**: Use NAS devices with SMB protocol

## Architecture

```
┌─────────────────────┐
│  SMB Server         │
│  (NAS/Windows)      │
└──────────┬──────────┘
           │ SMB/CIFS Protocol
           │
┌──────────▼──────────┐
│  CSI Driver         │
│  (DaemonSet)        │
└──────────┬──────────┘
           │
           │ Mount
           │
┌──────────▼──────────┐
│  Pod Volume         │
│  (Container Path)   │
└─────────────────────┘
```

## Prerequisites

- **SMB Server**: Windows file server, Samba server, or NAS with SMB support
- **Network Access**: Pods must be able to reach the SMB server
- **Credentials**: Username and password for SMB authentication (if required)
- **Privileged Namespace**: CSI drivers require privileged Pod Security level (managed by cluster-infrastructure deployment)

## Creating SMB PersistentVolumes

### Option 1: Static Provisioning (Recommended for existing shares)

Create a PersistentVolume and PersistentVolumeClaim:

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: plex-media
spec:
  capacity:
    storage: 10Ti
  accessModes:
    - ReadOnlyMany
  persistentVolumeReclaimPolicy: Retain
  mountOptions:
    - dir_mode=0755
    - file_mode=0644
    - uid=1000
    - gid=1000
  csi:
    driver: smb.csi.k8s.io
    readOnly: true
    volumeHandle: plex-media
    volumeAttributes:
      source: "//server.lan/media"
    nodeStageSecretRef:
      name: smbcreds
      namespace: plex
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: plex-media
  namespace: plex
spec:
  accessModes:
    - ReadOnlyMany
  storageClassName: ""  # IMPORTANT: Empty string prevents default StorageClass from being used
  resources:
    requests:
      storage: 10Ti
  volumeName: plex-media
```

**Important:** When using static provisioning with a default StorageClass in the cluster, you **must** set `storageClassName: ""` (empty string) in the PVC. Otherwise, Kubernetes will automatically assign the default StorageClass and the PVC won't bind to your static PV.

### Option 2: Dynamic Provisioning

Create a StorageClass for dynamic provisioning:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: smb
provisioner: smb.csi.k8s.io
parameters:
  source: "//server.lan/share"
  csi.storage.k8s.io/node-stage-secret-name: "smbcreds"
  csi.storage.k8s.io/node-stage-secret-namespace: "default"
mountOptions:
  - dir_mode=0755
  - file_mode=0644
```

## SMB Credentials Secret

Credentials are stored in a Kubernetes Secret:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: smbcreds
  namespace: plex
type: Opaque
stringData:
  username: "myuser"
  password: "mypassword"
```

**For production**, use VaultStaticSecret to fetch credentials from Vault (see plex deployment example).

## Deployment Environments

### Base Configuration (values.yaml)
- AppArmor disabled for CSI containers (required for mount operations)
- Minimal resource requests

### Production Configuration (values.prod.yaml)
- 2 controller replicas for high availability
- Increased resource limits

## Manual Deployment

```bash
# Update Helm dependencies
helm dependency update

# Deploy to production
helm upgrade --install \
  --create-namespace \
  --namespace csi-driver-smb \
  --values values.yaml \
  --values values.prod.yaml \
  csi-driver-smb .
```

## Verification

Check that the driver is running:

```bash
kubectl get pods -n csi-driver-smb
kubectl get csidrivers
```

You should see:
- `csi-smb-controller` pod running
- `csi-smb-node` pods running on each node
- CSI driver: `smb.csi.k8s.io`

## Troubleshooting

### Mount fails with "permission denied"

**Check:**
1. Credentials are correct in the secret
2. SMB server allows connections from cluster IPs
3. User has permission to access the share

### Mount fails with "host unreachable"

**Check:**
1. Network connectivity: `kubectl exec -it <pod> -- ping server.lan`
2. Firewall allows SMB traffic (TCP 445)
3. DNS resolution works for the server name

### Pods not starting - PodSecurity violation

**Error**: `pods is forbidden: violates PodSecurity "baseline:latest"`

**Cause**: CSI drivers require privileged access to mount volumes on host systems.

**Fix**: The namespace is configured by the `cluster-infrastructure` deployment. Ensure `cluster-infrastructure` has been deployed and synced:

```bash
# Check cluster-infrastructure is synced
kubectl get application -n argocd cluster-infrastructure

# Verify namespace has correct labels
kubectl get namespace csi-driver-smb -o yaml | grep pod-security
```

If the labels are missing, manually apply them:

```bash
kubectl label namespace csi-driver-smb \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/warn=privileged --overwrite
```

### AppArmor blocks mount

The driver requires AppArmor to be disabled:
```yaml
securityContext:
  appArmorProfile:
    type: Unconfined
```

This is configured by default in values.yaml.

## Mount Options

Common mount options:

- `dir_mode=0755` - Directory permissions
- `file_mode=0644` - File permissions
- `uid=1000` - Owner UID
- `gid=1000` - Owner GID
- `noperm` - Don't check permissions on server
- `vers=3.0` - Force SMB version (2.0, 2.1, 3.0, 3.1.1)

## Security Considerations

- **Credentials**: Never commit credentials to git - use Vault or sealed secrets
- **Read-only**: Mount media shares as read-only when possible
- **Network isolation**: Consider using NetworkPolicies to restrict SMB traffic
- **Encryption**: Use SMB 3.0+ for encryption in transit

## References

- [SMB CSI Driver Documentation](https://github.com/kubernetes-csi/csi-driver-smb)
- [Kubernetes CSI Documentation](https://kubernetes-csi.github.io/docs/)
- [SMB Protocol Documentation](https://docs.microsoft.com/en-us/windows-server/storage/file-server/file-server-smb-overview)
