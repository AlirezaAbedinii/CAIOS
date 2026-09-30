# The narrated recording

The five-minute walkthrough in `docs/demo-script.md`, recorded by a script on
the live platform, narrated by a synthetic voice, captioned, and cut together.
It came out at **4:03**. Nothing in it is mocked: every screen is the real
dashboard, chat, notebook or terminal, as the researcher and the administrator
see them.

```bash
bash demo/recording/run.sh build             # the two images, once (about 6 GB, on /mnt)
bash demo/recording/run.sh tts               # speak narration.yaml
python3 demo/recording/terminals.py up       # the terminals beats 4 and 6 use
bash demo/recording/run.sh setup             # sign the browser profiles in, off camera
bash demo/recording/run.sh record            # all sixteen clips, about 8 minutes
bash demo/recording/run.sh assemble          # about 7 minutes on this machine
bash demo/recording/run.sh readme-media      # logo, preview GIF, 720p video for the README
python3 demo/recording/terminals.py down
bash demo/recording/accounts.sh delete-all   # the colleague beat 2 created
```

Run it on `caios_server` with the recording's deployments staged, exactly as
`docs/demo-script.md` *Before you start* says. It installs nothing on the host:
the browser, ffmpeg and the voice run in containers, as you.

What comes out, in `out/final/` (gitignored, like everything in `out/`):

| File | What |
|---|---|
| `caios-demo.mp4` | 1080p30, H.264 and AAC, captions as a track the player can switch on |
| `caios-demo-captioned.mp4` | the same, with the captions burned in, for anywhere that ignores caption tracks |
| `caios-demo.srt`, `.vtt` | the captions on their own |
| `timeline.json` | where every clip and every line landed |

and `transcript.md` here, committed, with each line's timecode.

`readme-media` also writes `docs/assets/demo-preview.gif` (the README's 20-second
loop, one labelled moment per tier), the two README logos, and
`out/final/caios-demo-720p.mp4`: the captioned video under 10 MB. GitHub plays a
video inline in a README only when it was uploaded through its own editor, and
caps that upload at 10 MB, so that file is what goes in: open the release's edit
page on github.com, drop the file into its notes, save the release, and put the
`user-attachments` link on a line of its own in the README (D-89). An attachment
stays private until the form it was uploaded into is saved; one uploaded into a
form that was abandoned answers 404 however many public pages link to it.

---

## How it works

**The narration comes first.** `narration.yaml` is the only place the words
live. `tts.py` speaks each line with
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache 2.0, 82
million parameters, on CPU) and keeps each word's timing. The script's words
never leave `caios_server`; only the model weights were downloaded.

**The takes are paced by the voice.** `record.py` drives a real Chromium on a
virtual 1080p display while ffmpeg records it. `take.say("b3d")` notes the
moment a line starts and holds the next one until it has finished;
`take.word("b1c", "low")` waits for one word, which is how the home page's
tabs are clicked as they are named. Loads and waits are logged as cuts, the
federated rounds as a stretch to play at 2x.

**The edit follows the log.** `assemble.py` removes each cut with a short
dissolve, speeds up what was marked, places every line at the time its cue
mapped to, joins the clips with half-second dissolves, and writes captions
split into two balanced rows. It never lets two lines overlap; where a cut
pulls a line early it moves it later and says so.

**Retakes are cheap.** `run.sh record b3b` re-records one clip;
`run.sh assemble` rebuilds the whole video from whatever clips exist. Change a
line in `narration.yaml`, run `run.sh tts <line>`, retake the clip that says
it, assemble. The chat clip checks the model's answer and retakes itself, up
to four times, if the model declined the task instead of summarising: the
chat samples, and on one of the four takes on 2026-09-29 the 2B model refused.

**The pointer is drawn by the page.** Playwright's pointer is synthetic and a
virtual display has none, so an init script draws an arrow and a ring on each
click, moving the way a hand would. The chapter cards ("No code", "Low code"…)
are the same script.

### The profiles

| Profile | Who | For |
|---|---|---|
| `anon` | nobody, recreated at every take | beat 1 |
| `a` | the colleague who signs up (Maya Tremblay, `example.org`) | beat 2 |
| `b` | Platform Administrator | beat 2's approval |
| `c` | researcher (Dana Okafor) | beats 3 to 7 |

`setup` signs `b` and `c` in, including the chat and JupyterLab, so no password
is typed on camera except into the registration and sign-in forms, which mask
it. The colleague's password is random, in `out/newcomer.pw`, and the account
is in `out/accounts.txt`, which is the only list `accounts.sh` will delete from.

### The terminals

`terminals.py up` serves five real shells to the browser with
[ttyd](https://github.com/tsl0922/ttyd), on loopback only. One is
`caios_server` with the serverless endpoint and token already exported (the
token is never on screen); four are `nomad alloc exec` into the federated
server and the three hospitals. Beat 6 types the script's own commands into
them and waits on their real output.

---

## What the recording changes on screen, and why

Five things a viewer sees differently from a browser visiting the live
platform. Each is done by the recorder, in the page, for the take only:

| What | Why | The proper fix |
|---|---|---|
| The admin page's *Decided* list is blurred | it names real people and their email addresses | none needed |
| The module page's build badge is hidden | it is AI4EOSC's Jenkins, fetched from `jenkins.cloud.ai4eosc.eu` by the viewer's browser, and it reads *aborted* | stop rendering upstream's CI badge (a dashboard patch) |
| Open WebUI's *A new version is available* banner is hidden | it is about Open WebUI's release cycle, not the demo | turn off Open WebUI's update check in the LLM job template (TODO: confirm the variable; believed to be `ENABLE_VERSION_UPDATE_CHECK`) |
| A `TqdmWarning: IProgress not found` under the notebook's first cell is hidden | harmless, and red | add `ipywidgets` to the workspace, or filter the warning in `caios_demo.py` |
| The detection image is shown at 520 px high | the photograph is portrait and taller than the screen | none needed |

Things deliberately **not** hidden: the Flower deprecation notice in the
server's terminal, and a Python `DeprecationWarning` in each hospital's; both
scroll away within seconds at 2x.

And against `docs/demo-script.md`:

- The JupyterLab password is entered at `setup`, not on camera. The login page
  is Jupyter's unstyled default and added nothing.
- The notebook's cells are run one at a time, as each is described, rather
  than *Run All*, which finished before the narration reached the second cell.
- Beat 2 shows the access notice and the greyed-out menu instead of the
  waiting-room page. Reaching that page as a pending user also raises a red
  *No storage providers available* error, which is a real bug.
- Statistics stays on *Overview*. The *Datacenters* map's tiles come from
  `carto.com` and render *API KEY REQUIRED*.
- The close is a title card, not a roadmap line.

## Choices that are yours

**How CAIOS is said.** The voice spells it, C-A-I-O-S. Read as *KAY-oss* it
is heard as "chaos" (speech recognition wrote exactly that, and the video
opened on "This is chaos"). `out/samples/` has the three readings; the
lexicon in `narration.yaml` says how to switch.

**The voice.** `af_heart`, Kokoro's best-rated English voice. Others are one
line in `narration.yaml`: `am_michael` and `am_fenrir` are the male
voices closest in quality, `bf_emma` a British one. For a grant panel a paid
voice (ElevenLabs, or a person reading `transcript.md`) will sound warmer;
the timing follows whatever WAVs are in `out/audio/`, so a human read can be
dropped in line by line and assembled the same way.

## When a take goes wrong

| What you see | What it is |
|---|---|
| `b6a` times out waiting for `[ROUND 1]` | a hospital did not connect: `python3 demo/recording/terminals.py down`, then `up`, and retake |
| `b3b` retakes four times and fails | the model keeps declining; try again, or change the note in `record.py` |
| `b2a` fails at *Register* | `mtremblay` exists from an earlier take: `bash demo/recording/accounts.sh delete-all` |
| a clip shows a Keycloak login | its profile's session expired: `run.sh setup` |
| a frame is laid out too wide and cropped | `--window-size` is in scaled pixels: 1441 x 811 at a scale of 4/3 |
| `assemble` says a line was moved | a cut or speed-up pulled it into the previous line; harmless under a second |
