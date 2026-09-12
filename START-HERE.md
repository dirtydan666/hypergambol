# Start here

No coding required. You will not type a single command. Everything below is
done by clicking in a web browser.

---

## What this thing actually is

It's a **price camera with a bouncer.**

Every 15 minutes it looks at six stock tokens, writes down what they cost, and
compares that to what the real stock costs. If the two numbers are far apart,
that *might* be an opportunity.

The bouncer is the important half. Before anything gets written down as real,
it has to survive four checks — because when we did this by hand, four
"opportunities" turned out to be bad data. Apple looked 4.6% cheap. It wasn't.
The number was simply wrong, and two different price websites were wrong in the
same way at the same moment.

So the program's main job is not finding opportunities. It's **refusing to
believe things that aren't true**, and keeping a permanent, timestamped record
of both what it believed and what happened next.

After a week you'll be able to answer one question with evidence instead of
vibes: *does a real, tradeable gap ever actually show up?*

---

## What GitHub is, in one paragraph

GitHub is a free website that stores files. It also has a feature called
Actions, which is a **free robot that runs your program on a schedule, on
GitHub's computers.** Nothing gets installed on your Mac. Your laptop can be
closed. The robot runs every 15 minutes either way, and writes the results back
into your files so they pile up into a history.

That history is the valuable part. Every entry is stamped with the time GitHub
ran it, and you can't go back and fake those. When you eventually post about
this, "here's my record, including the times I was wrong" is worth more than
any screenshot.

---

## Setup — about 10 minutes

### 1. Make a GitHub account
Go to github.com and sign up. Free.

### 2. Make a new repository
Click the **+** in the top right → **New repository**.

- Name it whatever you like (`basis-harness` works)
- Choose **Private** for now
- Click **Create repository**

A "repository" is just a folder that lives on their website.

### 3. Put the files in
On your new empty repo page, click **uploading an existing file**.

Unzip the file I sent you, then drag **everything inside** the `signal-harness`
folder into the browser window. Not the folder itself — the contents.

Scroll down, click **Commit changes**.

> If the `.github` folder doesn't come along when you drag — some computers hide
> folders starting with a dot — tell me and I'll send you a different package.
> That folder is the one that tells the robot when to run.

### 4. Turn the robot on
Click the **Actions** tab at the top of your repo. GitHub will ask whether you
want to enable workflows for this repository. Say yes.

### 5. Check the settings before trusting anything
In the Actions tab, click **probe (run this first)** in the left sidebar, then
the **Run workflow** button on the right. Leave the dropdown on `perps` and run
it.

Wait about a minute, click into the run, and open the step called
**Check settings**. It prints a list.

Do the same thing again with the dropdown set to `tokens`.

**Copy both outputs and paste them to me.** Two settings in the program are
educated guesses right now — what the venue calls the Apple contract, and a
formatting detail about the tokens. If either is wrong the numbers come out
silently wrong, which is the worst kind of wrong. The probes tell us the real
answers and I'll correct the file.

### 6. Take the first picture
Actions tab → **capture** → **Run workflow**.

Wait a minute or two, then look in your repo for a new folder called `data`,
and a file in it called `candidates.jsonl`. It should have six lines. Each line
is one stock token, at one moment in time.

### 7. Leave it alone for a week
That's genuinely the whole job. The robot takes over from here.

---

## Do I need to pay for anything?

**Not to start.** Four of the six names (Apple, NVIDIA, Tesla, Robinhood) can be
checked against a crypto exchange that's free and needs no signup. Those work on
day one, no card, nothing.

The other two (the S&P 500 fund and GameStop) need a real stock-price feed,
which costs around $30–50/month. They'll show up as `no_reference` in the log
until you add one — that's the program telling you it doesn't have a reference
price, not an error.

My advice: run it free for a week first. If nothing interesting ever shows up in
four names, don't spend the $50.

---

## What you'll see in the log

One line per token per check. The part to look at is the status:

| What it says | What it means |
|---|---|
| `clean_no_trade` | Price checks out, gap is too small to be worth anything. **This is the normal result.** |
| `rejected` | The bouncer threw it out, and names which check failed. Good. This is the system working. |
| `not_fillable` | Looked like a real gap until we asked what it would actually cost to buy. Died there. |
| `tradeable` | A gap survived every check *and* an actual price quote. **Rare. Tell me if you see one.** |
| `no_reference` | No price to compare against — usually means no stock feed configured. |

If you go a whole week with zero `tradeable` lines, that is not a failure. That
is a $0 answer to a question that would have cost real money to answer by
trading.

---

## If something goes red

Failed runs show a red X in the Actions tab. Click the run, click the red step,
and copy the text. Paste it to me. Red is normal in the first day or two — it's
usually a setting, not a real problem.

---

## What's next after the first week

Once there's a real history, the same machinery extends to the things you
actually asked about: which wallets are consistently winning and what they're
buying, and which launchpads and pairing assets the money is rotating into.

Those aren't new programs. They're new things to watch, checked by the same
bouncer and scored on the same record. That's why we built this one first, even
though it's the boring one.
