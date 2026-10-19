# Stock Ledger: setup and demo guide

This guide gets the app running on your laptop for a client demo, takes about 15 minutes, and needs no coding.

## What this app is

- One computer runs the app. Everyone else (other PCs and phones) opens it in a web browser on the same Wi-Fi. Nobody installs anything on their own device.
- All data stays in one file on that computer (`data/stock.db`). No internet or cloud account is needed.
- At the client, the "one computer" will be their office PC. For the demo, it's your laptop.

## 1. Install Python (once)

1. Go to **https://www.python.org/downloads/** and download Python 3.12 (any 3.10 or newer works).
2. Run the installer.
   - **Windows:** on the first screen, tick **"Add python.exe to PATH"** before clicking Install. If you miss this, the app won't start; run the installer again and tick it.
   - **Mac:** just click through.

## 2. Get the app

- **With GitHub access:** open the repository page, click the green **Code** button, then **Download ZIP**.
- **If someone sent you a ZIP:** use that.

Unzip it somewhere simple, e.g. `C:\StockLedger` (Windows) or your home folder (Mac).
**Don't** put it on the Desktop or in Documents on a Mac with iCloud sync on. iCloud offloads files and the app becomes very slow to start.

## 3. Start it

- **Windows:** double-click **`start.bat`**.
- **Mac:** open Terminal, type `cd ` (with a space), drag the app folder into the Terminal window, press Enter, then run:
  ```
  ./start.sh
  ```

The **first start takes 1–2 minutes** because it installs what it needs. Later starts take a few seconds.

When it's ready, the window shows something like:

```
  First-time setup code: 3F9A2C
  Type it on the setup screen to create the first editor.
...
Uvicorn running on http://0.0.0.0:8000
```

**Keep this window open.** Closing it stops the app.

## 4. First-time setup

1. Open a browser and go to **http://localhost:8000**.
2. Enter the **setup code** from the window, your name, and a password (at least 4 characters).
3. You're logged in as an **Editor**.

The setup code only appears on a brand-new install. Only someone sitting at the computer can see it, so nobody else on the Wi-Fi can grab the first account.

## 5. Open it on a phone (worth showing in the demo)

1. The phone must be on the **same Wi-Fi** as the laptop.
2. Find the laptop's address:
   - **Windows:** open Command Prompt, type `ipconfig`, and look for **IPv4 Address**, e.g. `192.168.1.23`.
   - **Mac:** System Settings → Wi-Fi → Details → **IP address**.
3. On the phone, open **http://192.168.1.23:8000** (use your own number).
4. **Windows:** if a firewall popup appears when the app first starts, click **Allow** for **private networks**.
5. Optional: in the phone's browser menu, choose **Add to Home screen** and it opens like an app.

Office Wi-Fi often blocks phone-to-laptop connections. If the phone can't load the page, use your phone's **hotspot** for both the laptop and a second phone.

## 6. Suggested demo flow (about 15 minutes)

The app starts with the client's **27 items with HSN codes** already loaded, plus vendors (Shreya Alloy, A, B, C).

| # | Show | Where | What to point out |
|---|---|---|---|
| 1 | Users | **Masters → Users → + Add** | Add "Ramesh" as **Viewer**. Editors change data, viewers only look. |
| 2 | Opening stock | **Home → Opening Stock entry** | Brass Rod, 1000 kg. Go-live balances. |
| 3 | Purchase | **Purchase In** | Pick material and party (add a new party right from the picker), qty 500, bill no. |
| 4 | Labour Out | **Labour Out** | Vendor Shreya Alloy, Brass Rod, 600 kg. **Challan no. LO-0001 is automatic.** Stock drops. |
| 5 | Labour In, part | **Labour In → Shreya Alloy → LO-0001** | Finished 300 kg. "Still pending 300 kg." |
| 6 | Labour In, close | Same challan again | Finished 270, scrap 20, tick **"This challan is complete"**. The app shows **burn 10 kg (1.67%)**. Above 5% it warns. |
| 7 | Sale | **Sale Out** | Try to sell more than stock: **it refuses** with a clear message. Then a valid sale. |
| 8 | Stock | **Stock** | Raw / Finished / Scrap / Vendors tabs. Tap an item to see its full history. |
| 9 | Ledger | **Ledger** | Filters by type, date and search. Open an entry: **who** created or edited it, and when. Edit and delete are logged. |
| 10 | Reports | **Reports** | Item reconciliation, vendor pending + aging, burn %. **Export CSV** opens in Excel; **Print / Save PDF**. |
| 11 | Viewer | Log out (bottom of sidebar, or tap your name on a phone) → log in as Ramesh | No entry buttons, no edit or delete. Read-only. |
| 12 | Phone | Open the app on a phone | Same app, big buttons, made for the shop floor. |

Selling points:
- **Stock can never go negative** and is never typed in. It is always calculated from entries, so it can't drift.
- **Burn** is calculated automatically when a challan is closed.
- **Every change records who did it and when.**
- **Vendor aging** flags material out for 180+ days (amber) and 300+ days (red), ahead of the GST one-year limit for job work.
- **No internet needed and no monthly cost.** Data stays in their office, with a backup copy saved every day.

## 7. Reset after a practice run

To start fresh before the real demo:

1. Close the app window.
2. Delete the **`data`** folder inside the app folder.
3. Start the app again. You'll get a **new setup code** and an empty app (items and vendors reloaded).

## 8. If something goes wrong

| Problem | Fix |
|---|---|
| Windows: "Python not found" | Reinstall Python and tick **"Add python.exe to PATH"**. Then delete the `.venv` folder inside the app folder and run `start.bat` again. |
| "Address already in use" / port 8000 busy | The app is already running in another window. Use that one, or close it first. |
| Phone can't open the page | Same Wi-Fi? Correct IP? Firewall allowed? Try a phone hotspot (see section 5). |
| Forgot the password | In the app folder, run `.venv\Scripts\python main.py reset-password "Your Name" newpass` (Windows) or `.venv/bin/python main.py reset-password "Your Name" newpass` (Mac). |
| Lost the setup code | Close the window and start again; the code is printed again. |
| "Too many wrong tries" | 5 wrong passwords lock that name for 5 minutes. Wait, or restart the app. |

## 9. At the client (after they say yes)

Same steps on their **office PC**, plus:

1. Put the app in `C:\StockLedger`, run `start.bat`, and let the **owner** do the setup with their own name and password. Then add the other people in Masters → Users.
2. In the Wi-Fi router, give the office PC a **fixed IP address**, so the phone and PC link never changes.
3. Set the PC to **never sleep** (Settings → System → Power).
4. Make it start automatically: press **Win+R**, type `shell:startup`, and put a **shortcut to `start.bat`** in the folder that opens.
5. Rename vendors **A, B, C** to the real ones in **Masters → Vendors**.
6. Backups: the app saves a copy every day in `data\backups`. Once a week, also use **Masters → Download backup** and keep it on a pen drive or Google Drive. If the PC dies, that copy is the data.

More technical detail is in **README.md**.
