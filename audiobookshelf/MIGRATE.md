# Audiobookshelf Data Migration Guide

This guide covers migrating data from the old Audiobookshelf deployment to the new ArgoCD-managed deployment.

## Overview

The migration process:
1. Backup config and metadata from old deployment
3. Restore data to new volumes


## Prerequisites

- Access to the cluster with the old deployment
- `kubectl` configured for the cluster
- Sufficient disk space for backup tarball

## Data to Migrate

- `/config` - Audiobookshelf configuration
- `/metadata` - Book/podcast metadata and covers

**Note**: `/audiobooks` and `/podcasts` are on SMB shares and don't need migration.

## Step 1: Backup Old Deployment Data

### 1.1 Check Old Deployment

```bash
# Verify old deployment exists
kubectl get namespace audiobookshelf
kubectl get statefulset -n audiobookshelf
kubectl get pvc -n audiobookshelf
kubectl get pods -n audiobookshelf
```

**If the namespace doesn't exist**, there's no old deployment to migrate from. You can skip to Step 2.

### 1.2 Create Backup

```bash
# Get the old pod name
OLD_POD=$(kubectl get pod -n audiobookshelf -o name 2>/dev/null | head -1 | cut -d/ -f2)
echo "Using pod: $OLD_POD"

# Create backup tarball inside the pod
kubectl exec -n audiobookshelf $OLD_POD -- tar czf /tmp/audiobookshelf-backup.tar.gz -C / config metadata

# Copy backup to local machine
kubectl cp audiobookshelf/$OLD_POD:/tmp/audiobookshelf-backup.tar.gz ./audiobookshelf-backup.tar.gz

# Verify backup file
ls -lh audiobookshelf-backup.tar.gz
```

### 1.3 Scale Down Old Deployment

```bash
# Scale to 0 replicas to prevent data changes during migration
kubectl scale statefulset audiobookshelf -n audiobookshelf --replicas=0

# Verify it's stopped
kubectl get pods -n audiobookshelf
```

### 3.2 Create Restore Pod

Create a temporary pod that mounts the new volumes:

```bash
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: audiobookshelf-restore
  namespace: audiobookshelf
spec:
  containers:
  - name: restore
    image: busybox
    command: ['sh', '-c', 'sleep 3600']
    volumeMounts:
    - name: config-metadata
      subPath: config
      mountPath: /config
    - name: config-metadata
      subPath: metadata
      mountPath: /metadata
  volumes:
  - name: config-metadata
    persistentVolumeClaim:
      claimName: config-metadata-audiobookshelf-0
  restartPolicy: Never
EOF

# Wait for restore pod to be ready
kubectl wait --for=condition=Ready pod/audiobookshelf-restore -n audiobookshelf --timeout=60s
```

### 3.3 Copy and Extract Backup

```bash
# Copy backup tarball to restore pod
kubectl cp ./audiobookshelf-backup.tar.gz audiobookshelf/audiobookshelf-restore:/tmp/

# Extract backup into the new volumes
kubectl exec -n audiobookshelf audiobookshelf-restore -- tar xzf /tmp/audiobookshelf-backup.tar.gz -C /

# Verify data was restored
kubectl exec -n audiobookshelf audiobookshelf-restore -- ls -la /config
kubectl exec -n audiobookshelf audiobookshelf-restore -- ls -la /metadata

# Fix permissions (audiobookshelf runs as user 1000)
kubectl exec -n audiobookshelf audiobookshelf-restore -- chown -R 1000:1000 /config /metadata
```

### 3.4 Delete Restore Pod

```bash
# Clean up the restore pod
kubectl delete pod audiobookshelf-restore -n audiobookshelf
```

## Step 4: Start New Deployment

### 4.1 Scale Up New Deployment

```bash
# Start the new Audiobookshelf
kubectl scale statefulset audiobookshelf -n audiobookshelf --replicas=1

# Watch it start
kubectl get pods -n audiobookshelf -w
```

### 4.2 Verify Application

```bash
# Check logs for any errors
kubectl logs -n audiobookshelf -l app=audiobookshelf --tail=50

# Check the service
kubectl get svc -n audiobookshelf

# Check HTTPRoute
kubectl get httproute -n audiobookshelf

# Access the UI (if port-forward needed for testing)
kubectl port-forward -n audiobookshelf svc/audiobookshelf 8080:80
# Visit http://localhost:8080
```

### 4.3 Verify Data

1. Access Audiobookshelf UI at `https://audiobookshelf.rye`
2. Verify your libraries are intact
3. Check that metadata and covers are present
4. Test playback of an audiobook/podcast

## Step 5: Clean Up Old Deployment

**Only proceed if the new deployment is working correctly!**

### 5.1 Delete Old Deployment

```bash
# Delete the old Helm release
helm uninstall audiobookshelf -n audiobookshelf

# Or delete the StatefulSet if it wasn't a Helm release
kubectl delete statefulset audiobookshelf -n audiobookshelf
```

### 5.2 Delete Old PVCs (Optional)

```bash
# List old PVCs
kubectl get pvc -n audiobookshelf

# Delete old config-metadata PVC (NOT the new one!)
# Be careful to only delete the old PVC
# The old one might be named differently than config-metadata-audiobookshelf-0

# Example (verify the name first):
# kubectl delete pvc <old-pvc-name> -n audiobookshelf
```

### 5.3 Clean Up Backup File

```bash
# Delete local backup once everything is verified
rm ./audiobookshelf-backup.tar.gz
```

## Troubleshooting

### Pod Won't Start After Restore

```bash
# Check logs
kubectl logs -n audiobookshelf -l app=audiobookshelf

# Check PVC is bound
kubectl get pvc -n audiobookshelf

# Describe the pod for events
kubectl describe pod -n audiobookshelf -l app=audiobookshelf
```

### Permission Issues

```bash
# Create a debug pod to fix permissions
kubectl run -n audiobookshelf debug --rm -i --tty \
  --image=busybox \
  --overrides='
  {
    "spec": {
      "containers": [{
        "name": "debug",
        "image": "busybox",
        "stdin": true,
        "tty": true,
        "command": ["sh"],
        "volumeMounts": [{
          "name": "config-metadata",
          "mountPath": "/data"
        }]
      }],
      "volumes": [{
        "name": "config-metadata",
        "persistentVolumeClaim": {
          "claimName": "config-metadata-audiobookshelf-0"
        }
      }]
    }
  }'

# Inside the debug pod:
chown -R 1000:1000 /data
exit
```

### SMB Mount Issues

```bash
# Verify SMB secret exists
kubectl get secret smbcreds -n audiobookshelf

# Check if SMB PV is bound
kubectl get pv | grep audiobookshelf-data
kubectl get pvc audiobookshelf-data -n audiobookshelf

# Check Vault secrets are synced
kubectl get vaultstaticsecret -n audiobookshelf
kubectl describe vaultstaticsecret smbcreds -n audiobookshelf
```

### Data Not Showing in UI

```bash
# Exec into the running pod to verify data
POD=$(kubectl get pod -n audiobookshelf -o name 2>/dev/null | head -1 | cut -d/ -f2)
kubectl exec -n audiobookshelf -it $POD -- sh

# Inside the pod, check:
ls -la /config
ls -la /metadata
ls -la /audiobooks
ls -la /podcasts
```

## Rollback Plan

If the migration fails and you need to go back to the old deployment:

```bash
# Delete the new deployment via ArgoCD
kubectl delete application audiobookshelf -n argocd

# Wait for resources to be cleaned up
kubectl get all -n audiobookshelf

# Scale up old deployment (if still exists)
kubectl scale statefulset audiobookshelf -n audiobookshelf --replicas=1

# Restore from backup if needed (reverse of restore process)
```

## Notes

- The audiobooks and podcasts are on SMB (`nas.lan/media/audio.books`), so they don't need migration
- Only the config and metadata (stored in Longhorn volumes) need to be migrated
- The new deployment uses the same SMB source, so your media will automatically be available
- Make sure the Vault SMB credentials are correctly configured before starting
- The migration can be tested first on a dev environment if available
