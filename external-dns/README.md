# External DNS setup
This cluster is going to point to OpenSense unboud to update records.

https://github.com/crutonjohn/external-dns-opnsense-webhook



## Opensense setup
- Create a local user with a password in your OPNsense firewall. System > Access > Users
- Create an API keypair for the user you created in step 1.
- Create (or use an existing) group to limit your user's permissions. The known required privileges are:
    - Services: Unbound DNS: Edit Host and Domain Override
    - Services: Unbound (MVC)
    - Status: DNS Overview


kubectl create namespace external-dns

kubectl create secret generic external-dns-opnsense-secret \
--namespace external-dns \
--from-literal=api-url='https://your-opnsense-url' \
--from-literal=api-key='YOUR_API_KEY' \
--from-literal=api-secret='YOUR_API_SECRET'


## Debug

Had to make sure the service account had the right prems
```
kubectl auth can-i list endpointslices.discovery.k8s.io --as=system:serviceaccount:external-dns:external-dns
kubectl auth can-i list namespaces --as=system:serviceaccount:external-dns:external-dns
```
