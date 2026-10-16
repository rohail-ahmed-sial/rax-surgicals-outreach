# RAX Surgicals Outreach 1.0

**Find buyers. Email them. Turn replies into orders.**

Software for RAX Surgicals that finds new clients, emails them and handles their replies. On Windows it installs like any other program; the same program can also run on an online server.

## What it does

1. **Finds leads:** Google Maps search (several countries and cities at once), a pasted list of websites or emails, a CSV or Excel (.xlsx) file, or one company added by hand.
2. **Reads each company's website:** finds public business emails (sales@, info@, purchasing@ and so on), checks that the email's domain can receive mail, and keeps a short summary of the site.
3. **Judges the fit with AI:** good / maybe / no, with the reason. Other manufacturers from Sialkot are marked "no" automatically.
4. **Campaigns:** you describe the pitch. The AI writes a separate email and follow-ups for each company, using only the facts you entered in Settings.
5. **Approve:** you read and approve every first email. Spam words, emails that are too long, or leftovers such as "[Name]" are flagged first.
6. **Sending:** one email at a time, within a daily limit, a few minutes apart, during office hours in the recipient's country. A new mailbox starts slowly (warm-up).
7. **Inbox:** replies are grouped by company. The AI drafts your answer, and you attach the catalogue PDF and send it from the same screen. Interested replies can be forwarded to a colleague automatically.
8. **Pipeline:** Interested → Quote sent → Samples → Negotiation → Order won / Lost, with the deal value and the date of the next step.
9. **Safety:** sending pauses itself when too many emails bounce; bounced and unsubscribed addresses are never emailed again; your data is backed up every day.

## What is in version 1.0

- RAX Outreach is now called **RAX Surgicals Outreach**, with the slogan "Find buyers. Email them. Turn replies into
  orders." The new name is on the window, the icons, the setup and Windows Settings → Apps.
- Updating from 2.1 or earlier moves your data (leads, emails, settings, files and backups) and the Python that was
  already downloaded into the new folders, and removes the old icons. Nothing is downloaded again and nothing is lost.

## New in version 2.1

- The app and its setup open in a clean window of their own. Browser extensions (translators, AI helpers, ad
  blockers) no longer add their buttons and boxes to it, and the window opens at a size that fits the screen.
- The Python download during setup is more reliable: when the connection stops, it continues where it stopped
  instead of waiting; it shows the speed and the time left; if python.org does not work it tries a second server
  (NuGet); and a Python file you downloaded yourself can be used instead (see Troubleshooting).

## New in version 2

- New design, dark mode, and a layout that also works on a phone.
- A **setup guide** on first start: the mail servers for Gmail, Zoho, Outlook, Hostinger and cPanel fill in by themselves, with the App Password steps.
- **Today** page: what needs you now, the last 7 days, which countries are in office hours right now, charts, and the AI cost.
- **Approve** desk with keyboard keys: J/K next and previous, A approve, S skip, R rewrite with AI, T send a test to yourself.
- Answer replies in the **Inbox** with an AI draft, attachments and forwarding, and move the deal stage as you send.
- **Pipeline** board, notes, and the full history of every company.
- Warm-up, automatic pause on bounces, a mail-server check before sending, and an SPF/DKIM/DMARC check of your domain.
- Excel import (it recognises the columns), search ideas in the local language, and a history of your searches.
- A Windows setup program: its own window, Start menu and desktop icon, optional start with Windows, uninstall from Windows Settings.
- A daily automatic backup, and restoring a backup from Settings.

## Install on Windows

1. Double-click **`RAX-Surgicals-Outreach-Setup.exe`**.
   - Windows may say "Windows protected your PC", because the file has no paid code-signing certificate. Click **More info**, then **Run anyway**.
2. Choose whether you want a desktop icon and whether RAX Surgicals Outreach should start with Windows, then press **Install**. No administrator rights are needed. Setup downloads Python (about 11 MB) from python.org into the program folder; you do not install Python yourself. On a slow line this can take a few minutes; the setup window shows the speed and the time left.
3. Press **Open RAX Surgicals Outreach**. Next time, open it from the Start menu or the desktop icon.

- It opens in its own window, like any other program. The setup guide starts the first time.
- Closing the window does not stop it: it keeps sending emails at the right time in the background. To stop it completely, press the **power button** at the bottom of the menu.
- "Start with Windows" can be turned on or off later in **Settings → Sending and safety**.
- **Update:** run a newer `RAX-Surgicals-Outreach-Setup.exe`. It closes the running copy, replaces the program and keeps your data. An installed RAX Outreach (2.1 or earlier) is updated the same way: its data moves to the new folder.
- **Uninstall:** Windows **Settings → Apps → RAX Surgicals Outreach → Uninstall**. It asks whether to keep your data.
- Your data is in `%LOCALAPPDATA%\RAX Surgicals Outreach\data` (type that into the Explorer address bar). The program is in `%LOCALAPPDATA%\Programs\RAX Surgicals Outreach`. Messages and errors are written to `data\rax.log`.

## The zip version (servers, Mac, Linux, or if Setup does not work)

The zip runs the same program with your own Python 3.9 or newer (from https://www.python.org/downloads/; tick **"Add python.exe to PATH"** while installing).

- Windows: double-click `Start RAX Surgicals Outreach (Windows).bat`. It keeps a black window open while it runs.
- Mac or Linux: `sh start_mac_linux.sh`.
- A server: see `SERVER_SETUP.md`.
- The zip version keeps its data in the `data` folder next to the program.
- To update the zip version: stop it, unzip the new zip, copy the `data` folder from the old program folder into the
  new one, and start the new one. (Since 2.2 the zip's folder is called `RAX_Surgicals_Outreach`, not `RAX_Outreach`.)

## Moving your data

- **From the zip version (or version 1) to the installed app:** in the old version, use **Settings → Backup → Download a backup now** (in version 1, copy `data\outreach.db`). Then, in the installed app, use **Settings → Backup → Restore from a backup file**.
- Data from version 1 is upgraded automatically; a copy of it is kept in the backups folder first. Your settings stay, and the setup guide does not appear again.

## Setup

The setup guide asks for all of this the first time. You can change it later in **Settings**.

- **Company and facts:** what you make, who a good customer is, minimum order, lead time, samples, certificates, catalogue link. The AI only writes these facts; it does not mention anything you left empty.
- **Mailbox:** choose your provider (Gmail, Zoho, Outlook, Hostinger, cPanel) and the servers fill in by themselves. Then press "Send a test to myself" and "Test the inbox".
- **AI (Claude):** create an account at https://console.anthropic.com, create an API key and add a little credit (5 to 10 dollars is plenty to start). Checking one lead costs less than a cent; writing one email costs about a cent. "Most AI calls per day" caps the cost. Without a key the software still works: leads are checked by keywords and emails come from your own templates.
- **Google Maps:**
  1. Create a project at https://console.cloud.google.com.
  2. Add a billing account (Google includes a free monthly allowance).
  3. Enable "Places API (New)".
  4. Create an API key and restrict it to Places API (New).
  - Without it you can paste lists or import Excel/CSV files.
- **Sending and safety:** daily limit, warm-up, office hours, pause on bounces.
- **Forwarding:** send interested replies to another address automatically.
- **Files:** upload the catalogue, price list and certificates once; attach them to answers in the Inbox.
- **Password:** only needed when other people can reach your PC. Always needed on a server.

## Getting a business email

1. **Get a domain.** Your main website uses a domain like `raxsurgicals.com`. For cold emails, get a **separate similar domain** such as `raxsurgicals.co` or `getraxsurgicals.com`. If cold emails ever land in spam, only that second domain is affected. Point the second domain to your main website.
2. **Get a mailbox:** Google Workspace, Zoho Mail, Microsoft 365, or the email that comes with your hosting. Choose your provider in the setup guide.
   - **Gmail / Google Workspace:** your normal password does not work; create an **App Password** (turn on 2-Step Verification, then visit https://myaccount.google.com/apppasswords). The setup guide shows the steps.
3. **Add SPF, DKIM and DMARC** records to your domain's DNS. In Settings → Mailbox, "Is your domain ready for sending?" shows what is missing.
4. **Keep warm-up on.** A new mailbox starts at 10 emails a day and goes up every week. Do not send more than 40 to 50 a day from one mailbox.

## Daily work (10 to 15 minutes)

1. **Today:** look at "Needs you"; every item has its own button.
2. **Approve:** read the emails, change what you like, approve with `A`. Skip companies that do not look right with `S`.
3. **Inbox:** read the replies, press "Write with AI", attach the catalogue and send. Change the deal stage at the same time.
4. **Pipeline:** write the next step (samples, quote, call) and its date. On that date, the Today page reminds you.
5. Once or twice a week, run a new search in **Find leads** and add the ready leads to a campaign.

Tip: keep one kind of client per campaign (for example dental distributors in one, beauty wholesalers in another) so the pitch fits.

## Law and care

- Every cold email carries your address and an "unsubscribe" line automatically (US CAN-SPAM and the European/UK rules). Answers sent from the Inbox do not carry the unsubscribe line.
- Email companies only, not private people, and only business addresses the company published on its own website. In Europe this falls under "legitimate interest": the email is short, relevant to the company's business, and never sent again after a no. The software works this way.
- Taking data from LinkedIn (scraping) is against LinkedIn's terms, so the software does not do it.
- The AI can make mistakes, which is why every first email waits for your approval.

## Logo

The `logo` folder has the RAX Surgicals Outreach logo for use elsewhere (presentations, documents, your website): the icon as PNG and SVG, and the full logo with the slogan for light and dark backgrounds. The same icon is used for the desktop shortcut, the browser tab and the phone home screen.

## Data and backup

- All data is in the `data` folder (`data\outreach.db`). The software keeps a copy in `data\backups` every day.
- **Settings → Backup:** "Download a backup now" saves a file you can keep elsewhere (a USB stick or Google Drive). "Restore from a backup file" brings old data back.
- To get your leads in Excel, press "Export to Excel" on the Leads page.

## Running on an online server

See `SERVER_SETUP.md`. On a server the software runs 24 hours a day and opens on your phone too. Run it in one place at a time: on the PC or on the server.

## Troubleshooting

- **"Google did not accept the password":** use an App Password, not your normal password. Then press "Resume sending" on the Today page.
- **Sending is paused:** the Today page shows why (for example too many bounces, or a login problem). Fix it and press "Resume sending".
- **Why hasn't an email gone yet?** It is outside office hours in the recipient's country (night or weekend). The "When emails go out" chart on the Today page shows when it will go.
- **A website "did not open":** some websites block automated visits. Add that company's email by hand.
- **"Port 8765 is used by another program":** close the other program (or another copy of RAX Surgicals Outreach, such as the zip version), then open RAX Surgicals Outreach again.
- **Setup is stuck at "Getting the Python runtime ready", or says Python could not be downloaded:** download
  https://www.python.org/ftp/python/3.13.3/python-3.13.3-embed-amd64.zip in your browser, put the file in the same
  folder as `RAX-Surgicals-Outreach-Setup.exe` (or leave it in Downloads), and run the setup again. It uses that file and needs
  no internet.
- **Strange buttons or boxes in the window** (a translator, an AI icon): those came from extensions in your normal
  browser. Since version 2.1 the app opens in a window of its own without them; install the new version over the old
  one.
- **Anything else:** see the **Help** page in the dashboard and the `data\rax.log` file.
