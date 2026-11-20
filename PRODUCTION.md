# Running Stock Ledger for real (factory PC + Tailscale)

This guide sets the app up the way it should run day to day:

- **One Windows PC in the factory** runs the app and holds all the data (`data\stock.db`).
- **Factory staff on the Wi-Fi** open `http://<PC-IP>:8000` on their phones.
- **The owner, from anywhere** (on the road, at home, mobile data or any Wi-Fi) opens a private
  `https://stock.<something>.ts.net` link through **Tailscale**.
- **Every day** a backup is saved on the PC and copied to Google Drive.

```
Owner's phone, anywhere ── Tailscale (private, encrypted) ──┐
                                                            ▼
Factory phones ── factory Wi-Fi ──────────────────►  Factory PC: Stock Ledger app + data\stock.db
                                                            │ every day
                                                            ▼
                                        data\backups (30 days) + Google Drive copy (30 days)
```

Nothing is open to the public internet: no router ports, no DNS changes, no website. Tailscale's
free plan covers a small team; check tailscale.com/pricing for the current limits.

Plan for about **2 hours on site** the first time. Do the steps in order.

---

## 1. Prepare the PC

The PC must be on whenever someone might use the app.

- [ ] A PC or mini PC with **Windows 10 or 11**, an SSD and 8 GB of memory is plenty. Use it only for this
      if you can. Not someone's daily laptop.
- [ ] A **UPS**, so a short power cut doesn't switch it off.
- [ ] In the BIOS/UEFI setup, set **"Restore on AC power loss"** (sometimes "After power failure") to
      **Power On**, so it starts by itself when power comes back.
- [ ] Windows **Settings → System → Power**: Screen off is fine, but **Sleep: Never**.
- [ ] Windows **Settings → Windows Update → Advanced options → Active hours**: set to factory hours, so updates
      restart the PC at night. The app starts again by itself after a restart.
- [ ] Give the PC a **Windows password**. If it's Windows Pro, turn on **BitLocker** (Settings → Privacy &
      security → Device encryption / BitLocker) so the data is safe if the PC is stolen.
- [ ] In the Wi-Fi router, give this PC a **fixed IP** (called "DHCP reservation" or "static lease"), so
      `http://<PC-IP>:8000` never changes. Write the IP down.

## 2. Install the app

1. Install **Python 3.12** from python.org. On the first installer screen tick **"Add python.exe to PATH"**,
   then choose **Customize installation → Install Python for all users**.
2. Put the app folder at **`C:\StockLedger`**. Not the Desktop, Downloads or a OneDrive/Google Drive folder:
   sync apps and a live database don't mix.
3. Double-click **`start.bat`** once. The first run takes 1–2 minutes. The window shows a **setup code**.
4. On the PC open **http://localhost:8000**. Type the setup code, the **owner's name** and a **strong password**
   (8+ characters). The first person is the **Owner** with every permission.
5. **Close the `start.bat` window.** From now on the background service runs the app, so don't use
   `start.bat` again on this PC.

## 3. Run it in the background (starts with Windows)

1. Open `C:\StockLedger\windows` and double-click **`install-service.bat`**. Click **Yes** when Windows asks for
   admin permission.
2. After a few seconds it should say **"Stock Ledger is running"** in green.
3. **Test it:** restart the PC, **don't log in**, and open `http://<PC-IP>:8000` on a phone on the factory Wi-Fi.
   The app should load. That proves it starts by itself.

The other buttons in the `windows` folder:

| File | What it does |
|---|---|
| `restart-service.bat` | Restart the app, after changing `settings.ini` or updating. |
| `stop-service.bat` | Stop it, e.g. before restoring a backup. |
| `uninstall-service.bat` | Remove the background service. The data stays. |

If it says *not answering*, look in **`C:\StockLedger\data\logs`**: `app.log` and `server.log` say why.

> These scripts haven't been run on a real Windows PC yet. If one of the steps above doesn't give the result
> it describes, note the exact message and the contents of `data\logs` before changing anything.

## 4. Users and permissions

The owner sets these in **Masters → Users**. Tick what each person may do. Everyone can look at Stock, Ledger and Reports.

| Tick | Allows |
|---|---|
| Add & edit entries | Purchase In, Labour Out/In, Sale Out, Opening Stock; editing entries; adding parties |
| Delete entries | Deleting entries. A reason must be given; it's kept with the entry |
| Manage masters | Materials, types, grades, vendors |
| Owner | Users and permissions, backups |

For this factory: tick **Add & edit entries** for the 2 people who make entries, and **Delete entries** for
the 1 person who may delete. The server checks these on every request, so a change applies immediately,
even on a phone that is already logged in.

- Deleted entries never disappear. In **Ledger**, tap **Show deleted** to see them, with who deleted them and why.
- **Forgot a password?** The owner sets a new one in Masters → Users. **Owner forgot theirs?** On the PC, open
  **Command Prompt as administrator** and run:
  ```
  cd C:\StockLedger
  .venv\Scripts\python main.py reset-password "Owner Name" new-password
  ```

## 5. Access from outside the factory (Tailscale)

Tailscale makes a private, encrypted network between the factory PC and the owner's phone. Only devices
signed in to the factory's Tailscale account can reach the app. To everyone else on the internet it doesn't exist.

**Once, on the factory PC:**

1. Create a Tailscale account at **tailscale.com** using the **owner's** Google or Microsoft account.
2. Download and install **Tailscale for Windows** on the factory PC and sign in with that account.
3. Click the Tailscale icon near the clock → **Preferences** → tick **Run unattended**. Without this it
   stops working when nobody is logged in to Windows.
4. Open the admin console at **login.tailscale.com/admin/machines**:
   - Factory PC → **⋯ → Edit machine name** → `stock` (this becomes part of the link).
   - Factory PC → **⋯ → Disable key expiry**. **Important:** otherwise the PC drops off every few months and
     remote access silently stops.
5. Admin console → **DNS**: turn on **MagicDNS**, and under it **Enable HTTPS** (HTTPS certificates).
6. On the PC, open **Command Prompt as administrator** and run:
   ```
   tailscale serve --bg 8000
   ```
   It prints the app's private link, like **`https://stock.tail1234.ts.net`**. Write it down. It keeps working
   after restarts. Check it any time with `tailscale serve status`.

**On the owner's phone:**

1. Install the **Tailscale** app (Play Store / App Store), sign in with **the same account**, and switch it **on**.
2. Open the `https://stock.….ts.net` link and log in to Stock Ledger. Use **Add to Home screen** for an app icon.
3. **Test it:** turn the phone's Wi-Fi **off** and open the icon on mobile data. It should load.

**Day to day:** Tailscale stays on in the background on the phone (it uses very little battery). If the link
doesn't open, open the Tailscale app and check it's switched on.

**Someone else needs remote access?** In the admin console use **Share** on the factory PC and send the link to
their own Tailscale account. Sharing gives them only this PC, nothing else on the network. A lost phone:
admin console → Machines → that phone → **Remove**, and the owner changes that person's app password.

**When remote access doesn't work:** the factory PC must be on and have internet. If the factory internet
is down, the app still works on the factory Wi-Fi, and the owner can reach it again once it's back.

## 6. Off-site backup (Google Drive)

Every day the app saves a copy in `C:\StockLedger\data\backups` (last 30 days). That doesn't help if the PC
is stolen or its disk dies, so a second copy goes to Google Drive.

1. Install **Google Drive for desktop** on the factory PC and sign in with the owner's Google account.
   Turn on **2-Step Verification** for that Google account. The backups hold all the data.
2. Google Drive → **Settings (gear) → Preferences → My Drive → Mirror files**. This keeps a real folder at
   `C:\Users\<you>\My Drive` that the background app can write to. (The default "Stream files" mode uses a
   G: drive the background app can't see.)
3. In `C:\StockLedger`, copy `settings.example.ini` to **`settings.ini`**, open it in Notepad, and change the
   backup line to (remove the `;` in front, use your Windows user name):
   ```
   offsite_dir = C:\Users\<you>\My Drive\Stock Ledger Backups
   ```
4. Run **`windows\restart-service.bat`**.
5. In the app, **Masters → Backup** should now show today's date for both **On this PC** and **Off-site**. If
   Off-site is red, the message under it says why.

Google Drive uploads only while someone is logged in to Windows (a locked screen is fine). Copies made while
nobody is logged in upload at the next log-in. The owner should glance at **Masters → Backup** once a week.

## 7. Restore drill (do it once now, then every few months)

Practise on **another computer** so the real one keeps running:

1. Copy the app folder to that computer (without the `data` folder).
2. From Google Drive, copy the newest `auto-YYYY-MM-DD.db` into a new `data` folder there and rename it
   to **`stock.db`**.
3. Run `start.bat` there, open http://localhost:8000, log in, and check stock and the last entries look right.

To restore **for real** on the factory PC: run `windows\stop-service.bat`, then in `C:\StockLedger\data`
rename `stock.db` to `stock-broken.db` and **delete `stock.db-wal` and `stock.db-shm` if they exist**, copy the
backup in as `stock.db`, and run `windows\restart-service.bat`. Entries made after that backup must be entered again.

## 8. Updating the app later

1. In the app, **Masters → Download backup**, just in case.
2. Replace the app files in `C:\StockLedger` with the new version. **Keep** the `data` folder, `.venv` and
   `settings.ini`.
3. If `requirements.txt` changed, open Command Prompt in `C:\StockLedger` and run
   `.venv\Scripts\python -m pip install -r requirements.txt`.
4. Run **`windows\restart-service.bat`**. Any database changes happen by themselves on start.

## 9. Security checklist

- [ ] Each person has their own login and a password nobody else knows. 8+ characters for the owner and anyone who can delete.
- [ ] Only the people who need it have **Add & edit**, **Delete** or **Owner** ticked.
- [ ] Factory Wi-Fi has a strong password. Visitors use a separate guest Wi-Fi.
- [ ] Tailscale: factory PC key expiry **disabled**, and only the owner's devices (or shared people) on it.
      Lost phones removed.
- [ ] Google account with the backups uses 2-Step Verification.
- [ ] Masters → Backup shows today's date for both copies.
- [ ] Restore drill done.
