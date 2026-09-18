# Troubleshooting

Roughly in the order things go wrong. Every step here is something you can check yourself before filing an issue — and if you do file one, the output of these commands is what makes it fixable.

## `padmap devices` finds nothing

The controller is not reaching SDL at all. padmap is not involved yet.

- **Wired**: try a different USB port and cable. Xbox pads need a data cable; some charge-only cables look identical.
- **Bluetooth**: confirm the pad is actually *paired and connected*, not just paired. The Xbox button stays lit when connected.
- **Linux**: the `xpad` kernel driver handles Xbox pads. Check it loaded with `lsmod | grep xpad`, and that a device node exists at `/dev/input/js0` or `/dev/input/event*`. If the node exists but your user cannot read it, you are missing the `input` group: `sudo usermod -aG input $USER`, then log out and back in.
- **Windows**: check the pad appears under Settings → Bluetooth & devices. If Windows sees it and padmap does not, it is usually a stale `pygame` install — `pip install --upgrade pygame`.

## `padmap devices` finds it, but nothing happens when I run

Input is being generated but the OS is refusing to deliver it. This is the single most common problem, and it is a permission issue every time.

| Platform | Cause | Fix |
| --- | --- | --- |
| **macOS** | The terminal lacks Accessibility permission | System Settings → Privacy & Security → Accessibility → add and enable your terminal app. Restart the terminal afterwards; the permission is read at launch. |
| **Linux (Wayland)** | Wayland compositors reject synthetic input from ordinary processes | Log into an X11/Xorg session at the login screen. There is no workaround from inside padmap. |
| **Linux (X11)** | Usually nothing — this combination works | If it doesn't, check `echo $DISPLAY` is set. |
| **Windows** | An elevated window is in focus | A non-elevated process cannot send input to an elevated one. Run padmap as administrator *only* if you need it for a specific elevated app. |
| **Games** | Anti-cheat blocks synthetic input by design | padmap cannot work around this and will not gain features that try. |

Confirm padmap's own side is fine first:

```
padmap run --dry-run
```

If the dry run prints events as you press buttons, padmap's mapping is working and the problem is entirely on the delivery side — go back to the table above.

## It types into my own terminal

Because your terminal is the focused window. padmap injects at the OS level, so everything it sends goes wherever focus is — exactly like a real keyboard would.

```
padmap run --delay 3     # counts down; click into another window first
padmap run --detach      # better: hands the session off and frees the terminal
```

With `--detach` the terminal is free immediately and you can close it. Check on it with `padmap status`, shut it down with `padmap stop`.

## I closed the terminal and it stopped

Only a foreground session dies with its terminal. `padmap run --detach` starts it in its own session so it survives. If you want it back under your eye, `padmap stop` then `padmap run` again.

## Is it even running?

```
padmap status
```

Tells you the pid, the profile, how long it has been up, and where its log is. If it says a previous session "exited", read that log — it stopped on its own and the reason will be in there.

A foreground `padmap run` also prints a live status line showing the profile, the held layer, the precision modifier, the drift being corrected, and the number of events actually sent. If the event count is not climbing while you press buttons, padmap is not seeing the pad — go back to `padmap devices`.

## `padmap stop` says it did not exit

padmap releases every held key before exiting, so give it a second. If it is genuinely wedged, kill it by the pid `padmap status` reports. The stop request stays pending, so the session will still notice it if it comes back to life.

## The wrong button does the wrong thing

Drivers disagree about which raw index is which physical button. Find out what yours actually reports:

```
padmap monitor
```

Press each button and note the index it prints. Then pin the ones that are wrong in your profile:

```json
"device": {
  "layout": { "a": 0, "b": 1, "x": 2, "y": 3 }
}
```

`padmap validate <your-profile.json>` confirms the file still parses.

## The triggers are half-pressed at rest, or only work in the top half

Most drivers report the triggers as `-1` (released) to `1` (pulled); a few use `0` to `1`. padmap samples them at startup to decide which, but the guess can go wrong if a trigger is held while padmap starts. Pin it:

```json
"device": { "trigger_mode": "signed" }
```

Use `"unipolar"` for the other convention, or `"auto"` (the default) to go back to detection. `padmap monitor` shows the resting value: `-1.00` means signed, `0.00` means unipolar.

## The pointer drifts when I'm not touching the stick

Calibrate. Do not reach for the deadzone — a deadzone is centred on zero and a worn stick is not, so hiding 0.18 of drift costs you 0.18 of travel on the side that was never wrong.

```
padmap init mine.json
padmap calibrate --write mine.json
padmap run -p mine.json
```

padmap already auto-centres at startup, so if it is still drifting after that, one of these is true:

- **You were touching a stick when it started.** Auto-centring refuses a reading that looks held or moving, and says so in the terminal. Let go and restart.
- **`auto_centre` is off** in your profile. Set it back to `true`, or run `padmap calibrate` and store real numbers.
- **The drift is on a stick you never centre-calibrated, and the stored calibration overrides it.** Re-run `padmap calibrate --write`.

Drift also shows up as *skew* — push straight right and the pointer creeps upward. That is the other axis drifting, and calibration fixes it the same way.

## The pointer wobbles while I hold a direction

That is stick noise reaching the pointer. Raise `smoothing`:

```json
"sticks": { "left": { "mode": "mouse", "smoothing": 0.5 } }
```

`0` is off, `0.35` is the default, above `0.6` starts to feel laggy rather than steady.

## The pointer is too fast, too slow, or too twitchy

Five dials, and they do genuinely different things. Change one at a time — and run with `-w` so you can edit the file and feel the change without restarting.

- **`speed`** — pixels per second at full deflection. The baseline.
- **`accel`** — how much faster it gets while you hold the stick out. If crossing the screen is slow *but* fine positioning is fine, raise this, not `speed`.
- **`precision`** — how much slower it gets while a `special:precision` button is held. If fine positioning is hard *but* travel is fine, lower this and bind the modifier.
- **`curve`** — shapes the middle of the range. `1.0` linear, `2.0` (default) slow and precise near centre, below `1.0` twitchier.
- **`smoothing`** — steadiness, not speed. See above.

If it feels *twitchy right off centre*, that is usually drift rather than tuning — calibrate first.

Raising `poll_hz` (up to 200 or so) makes motion smoother, not faster.

## My profile stops working when I hold a button

You are probably in a layer. A button bound to `special:layer:<name>` swaps in a second set of bindings while held — `padmap validate <profile>` prints every layer and what it overrides. The bundled `desktop` profile puts a `nav` layer on **RB** and the precision modifier on **LB**.

## Editing the profile means restarting every time

It doesn't:

```
padmap run -w -p mine.json
```

`-w` reloads on save. A broken edit is printed and ignored, and the last working profile keeps running.

## A key is stuck down

Press the pause button on the pad (**Back / View** in every bundled profile), or `Ctrl-C` in the terminal — both release everything. If a modifier is genuinely still held afterwards, tap it on your physical keyboard to clear the OS's idea of its state.

Then please report it through [private vulnerability reporting](https://github.com/Ranzlappen/controller/security/advisories/new) rather than a public issue: a stuck modifier reinterprets every subsequent keystroke, which makes it the most serious class of bug padmap can have. Include the profile and what you were doing.

## A profile won't load

`padmap validate <file>` prints the exact path of the problem — `sticks.left.curve: 9.0 is out of range [0.1, 6.0]`. padmap rejects unknown keys on purpose: a typo that got silently ignored would look exactly like broken hardware.

Common ones:

- A trailing comma, or a comment. Profiles are strict JSON; `//` comments are not allowed.
- `turbo` and `toggle` on the same binding — deliberately rejected, since a latched auto-fire is a footgun.
- A key name padmap doesn't know. The error lists every valid name.
- `special:layer:<name>` pointing at a layer that isn't defined, or a layer nothing switches to. Both are rejected on purpose: at runtime a dangling layer switch is silent, which looks exactly like a broken button.
- A `special:` action inside a layer. Specials live in the base profile only.

## Still stuck

Open a [bug report](https://github.com/Ranzlappen/controller/issues/new/choose) with your profile, the output of `padmap devices`, and your platform. The issue template asks for exactly those.
