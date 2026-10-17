# Moving ColdOps from Hetzner to Oracle Cloud (Always Free)

Mail goes out through Google Workspace, so the server's address has nothing to
do with sending reputation: moving does not reset warm-up. What a move costs
is the hours nothing runs, so it is done in one sitting.

## 1. Create the server (operator, Oracle console)

1. Sign up at https://www.oracle.com/cloud/free/ with a home region in Europe
   (Frankfurt or Amsterdam). The home region cannot be changed later.
2. Compute -> Instances -> Create instance:
   * Image: **Canonical Ubuntu 24.04**
   * Shape: **Ampere VM.Standard.A1.Flex**, 4 OCPUs, 24 GB memory
     ("Out of capacity" means try again later or another availability domain.)
   * Networking: keep "Assign a public IPv4 address" on
   * SSH keys: "Paste public key", the contents of `~/.ssh/titan_hetzner.pub`
   * Boot volume: 200 GB
3. Open ports 80 and 443: Instance -> Subnet -> Default Security List ->
   Add Ingress Rules: source `0.0.0.0/0`, TCP, destination ports `80,443`.
4. Optional but recommended: upgrade the account to Pay As You Go (still free
   inside the Always Free limits), so Oracle never reclaims the server as idle.

## 2. Rehearse (laptop; the old server keeps running)

    sh deploy/oracle/move.sh <oracle-ip>

Installs Docker, builds the ARM images, restores every database and file, checks
the restored counts match the old server, and stops again. Nothing is sent.

## 3. Choose the moment

Any time outside 09:00-17:00 UTC (the warm-up hours) and away from 07:20 UTC
(the inbox test). The move takes about 30 minutes.

## 4. Stop the old server's work (operator, on Hetzner)

    ssh -i ~/.ssh/titan_hetzner root@168.119.161.220 "systemctl stop coldops-heal.timer coldops-backup.timer && cd /opt/coldops && deploy/compose.sh stop nginx web api outbox-worker inbound-worker temporal-worker browser-worker temporal"

The databases stay up for the final copy.

## 5. Move (laptop)

    sh deploy/oracle/move.sh <oracle-ip> --final

Refuses to run while the old server is still working. Ends with every container
listed as healthy.

## 6. Point the domain at Oracle (operator, Namecheap)

Advanced DNS for arslanvuzmallone.com: change the **A records** for `coldops`
(and `titan`, if present) from `168.119.161.220` to the Oracle IP.
Nothing else changes -- the MX, SPF, DKIM and DMARC records belong to Google.

## 7. Afterwards

* The certificate renews by itself once DNS points at Oracle (certbot.timer).
* Keep Hetzner until a day has run cleanly on Oracle, then cancel it.
* Deploys are as before with the new address: `ssh -i ~/.ssh/titan_hetzner ubuntu@<oracle-ip>`, `sudo -i`, `cd /opt/coldops`.
