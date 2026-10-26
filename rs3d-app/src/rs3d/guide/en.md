# RS3D Guide

Short version of the project Manual (`docs/Manual.odt`). The Status page tells you which section you need.

## 1. Connect

1. Put the Shake on a solid, level floor, away from doors, fans and footsteps.
2. Connect the Shake's Ethernet port directly to the laptop with a cable.
3. Power the Shake and wait 3–5 minutes.
4. Open **Status**. If **Laptop IP** is red, press **Set IP**.

The Shake gives itself a `169.254.x.x` address (ours: `169.254.221.62`, name `rs.local`).

## 2. Add the Shake to the app

- Use **Find Shake…** in the sidebar, or
- open **Settings**, enter the IP, the SSH user (`myshake`) and password, then **Test connection**.

The password is stored in your operating system's password store, never in a file.

## 3. Status checks

| Check | Meaning |
|---|---|
| Laptop IP | the laptop has a `169.254.x.x` address on the cable |
| SeedLink | live data port 18000 answers |
| Channels | EHZ, EHN, EHE are served |
| SSH | the app can log in to read clock, storage and archive |
| Clock | time offset and time source of the Shake |
| Internet / Wi-Fi | the Shake reaches the Internet (for its clock) |
| Storage | free space on the Shake's SD card |
| Archive | days stored on the Shake and how long it keeps them (RS3D expects 30) |
| Data Forwarding | public data sharing is off |
| Password | the default password was changed |

Hover a **(?)** for a hint, click it for the full explanation and fix.

## 4. Live

Three channels in real time. Choose the window (30 s, 60 s, 5 min), switch the 1–10 Hz filter on or off, pause, and use **Save this segment** to open the same range on the Data page.

The **Helicorder** page shows one day of one channel as 48 rows of 30 minutes (it reads the files in the local store, so download the day first).

## 5. Data

1. Choose **Start** and **End**, use **Presets**, or drag on the coverage bar.
2. **Download & preview** copies from the Shake only the part of each day file that covers your Start–End (the line above the button says how many parts and about how many MB). Parts you already have are not copied again.
3. Choose channels, band-pass filter and units (counts or m/s).
4. Export as **miniSEED**, **CSV**, **PNG**, **PDF**, or get the **Code** (ObsPy) to reproduce it.

The Shake deletes old days after its retention (RS3D expects **30 days**; the Status page warns if it is lower): download the days you need before they go.

## 6. Frequencies

Use this page to find the frequencies a structure (a floor, a room, a building) vibrates at.

1. Put the Shake on the structure and record for a few hours, ideally without people walking near it. Download the data on the **Data** page.
2. Open **Frequencies**. Choose the station, **Start** and **End** (or a preset), the units, and the **Channel** (Z, N or E). The page draws that channel for that range. Press the crop button and drag across the waveform to **box zoom**: Start and End follow the zoom, and the fit button goes back to the range you chose.
3. Press **Find frequencies** to analyse the channel and range on screen. Read the sentence at the top: *stable frequencies* are peaks present in at least 80 % of the blocks. Below it are the PSD graph (power against frequency, peaks labelled; Linear or Log) and a table with each peak's contrast, how often it appears and how much it moves.
4. Export the picture (**PNG**, **PDF**) or the numbers (**Peaks .csv**, **Spectra .csv**).

A stable peak is a *candidate*: it may be the structure, or a machine, pump or fan. Switch the suspect off and on, or measure on another floor, to be sure. Method: the range is cut into blocks of 5–30 minutes (about 20 blocks), each block gets a Welch spectrum (Hann window, 50 % overlap), the page shows the median and the 10–90 % band, and picks peaks that rise at least 6 dB above their surroundings between 0.7 and 35 Hz. Blocks with gaps or with samples at the digitizer limit are skipped. Developer notes: `docs/dev/frequencies.md`.

## 7. Events

RS3D can tell you when the ground shakes harder than usual. It uses the same STA/LTA trigger as rsudp: it compares a short average (STA, 6 s) with a long average (LTA, 30 s) of the vertical channel (EHZ) after a 0.8 to 9 Hz band-pass. When the ratio rises above **On** (3.95) an event starts; when it falls below **Reset** (0.9) it ends.

- **Live page:** a red banner appears at once ("Event in progress…"), turns orange when the event ends, and stays until you press **Dismiss**. The chart shades the event and a short list shows the latest events.
- **Data page:** each time you preview or download a range, the days in it are scanned with the settings in force at that moment. Events are shaded on the preview. **Rescan** runs the detector again on the selected days.
- **Helicorder:** events are shaded on their rows. Click one to open the detail view.
- **Settings → Events:** switch detection on or off and change channel, STA, LTA, On, Reset and the band-pass. Changes apply to the live detector at once; they never re-scan old data on their own, only the next preview, download or **Rescan** uses them.

The detector stays quiet for the first LTA seconds after start-up or after a gap in the data. When a day is scanned, the detector warms up on the stretch of twice the LTA before that day. Events are saved in `events.jsonl` in the data folder. Sound, desktop notification and email are planned.

## 8. Clock

The Shake keeps time with `ntpd`, from Internet servers over Wi-Fi, with the laptop (`169.254.8.11`) as a backup. Check on the Shake:

```
ntpq -pn
```

A line starting with `*` is the selected source; `offset` is in milliseconds.

### When the clock is wrong

The Shake has no battery clock, so after a power cut it restarts with an old time until its time service (ntpd) reaches a source. Each time you open **Status**, RS3D also compares the Shake's time with this laptop's time. If the Shake is off and has no time source, the Clock row turns yellow or red and shows a **Sync clock** button. The button also appears when the Shake is within 1 second of the laptop but has no time source at all (a red "no time source" row), because it will drift again.

1. Press **Sync clock**. The dialog shows how far the Shake is behind or ahead of the laptop.
2. Press **Sync now**. RS3D restarts the Shake's time service, which sets the clock from the laptop or from the Internet (Wi-Fi). It waits about 30 seconds.
3. If that does not work, **Set from laptop** appears. It copies this laptop's UTC time to the Shake. Use it only when this laptop's clock is right.

Changing the time can leave a small gap or overlap in the data. Data recorded while the clock was wrong keeps its wrong timestamps. If the Shake has a time source and only this laptop disagrees, RS3D shows a warning and no button: check the laptop's clock instead. Every attempt is written to `logs/clock-sync.log` in the data folder.

## Wi-Fi: two addresses

If `ip -4 addr show wlan0` on the Shake lists two addresses, Internet comes and goes. Two DHCP clients manage `wlan0`. Fix on the Shake:

```
sudo cp -p /etc/dhcpcd.conf /etc/dhcpcd.conf.bak-rs3d
sudo sed -i '/^denyinterfaces wlan0$/d' /etc/dhcpcd.conf
sudo sed -i '1i denyinterfaces wlan0' /etc/dhcpcd.conf
sudo reboot
```

Saving network settings in the Shake web page may bring the problem back.
