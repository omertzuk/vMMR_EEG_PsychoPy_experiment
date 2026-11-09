"""
generate_trials.py -- command-line version of conditions/generate_trials.ipynb.

Generates the vMMR trial tables read by run_vMMR_experiment_v2.py:
    conditions/main_trials.csv       (360 trials, per-participant seed)
    conditions/practice_trials.csv   (16 trials, fixed seed 99)
plus archive copies in conditions/generated/, then runs the diagnostics.

The trial logic is a line-by-line port of the notebook (cell 1 = main, cell 2 =
practice, cell 4 = diagnostics) with the same random-number call order, so the
same participant/seed gives the same trials. Differences from the notebook:
  * image paths are RELATIVE to the project root (POSIX, e.g.
    "stimuli/faces/GenAI_faces/self.png"), so the tables work on any computer;
  * extra columns at the end: participant, seed, facesDir;
  * practice uses random.Random(99) instead of the global random.seed(99)
    (identical sequence of numbers).
Standard library only; Pillow is used for the image check if installed.

USAGE (run from anywhere; paths are resolved from this file's location)

  Windows (lab PC, in the project .venv):
    .venv\\Scripts\\python conditions\\generate_trials.py --participant 1
    .venv\\Scripts\\python conditions\\generate_trials.py --participant 2 --faces-dir stimuli/faces/sub-002
    .venv\\Scripts\\python conditions\\generate_trials.py --check-only

  macOS:
    python conditions/generate_trials.py --participant 1
    python conditions/generate_trials.py --check-only

Options:
  --participant N   participant number; seed = base_seed + N (required unless --check-only)
  --faces-dir DIR   face-image folder, relative to the project root
                    (default stimuli/faces/GenAI_faces)
  --base-seed S     default 42 (as in the notebook)
  --check-only      only run the diagnostics on the existing CSVs
  --overwrite       allow replacing existing archive copies in conditions/generated/

Exit code 1 if a hard diagnostic rule fails (nothing is written in that case).
Hebrew words are never printed (Windows console encoding); only numbers.
"""

import argparse
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# =============================================================================
# Constants (identical to notebook cell 1)
# =============================================================================
N_BLOCKS             = 3
TRIALS_PER_BLOCK     = 120
TARGET_PER_BLOCK     = 30
NONTARGET_PER_BLOCK  = TRIALS_PER_BLOCK - TARGET_PER_BLOCK   # 90
CONDITIONS   = ['DS', 'DO', 'NS', 'NO']
DIAGONALS    = [('DS', 'NO'), ('DO', 'NS')]
PRIME_MAP    = {'DS': 'DEATH', 'DO': 'DEATH', 'NS': 'NEGATIVE', 'NO': 'NEGATIVE'}
IDENTITY_MAP = {'DS': 'SELF',  'DO': 'OTHER', 'NS': 'SELF',     'NO': 'OTHER'}

PRACTICE_SEED = 99
DEFAULT_BASE_SEED = 42
DEFAULT_FACES_DIR = "stimuli/faces/GenAI_faces"
FACE_FILES = ["self.png", "other.png", "morph50.png",
              "self_target.png", "other_target.png", "morph50_target.png"]
EXPECTED_FACE_SIZE = (425, 405)
EXPECTED_FACE_MODE = "L"

NOTEBOOK_COLS = ['block', 'trial_in_block', 'condCode', 'primeType', 'identity',
                 'word', 'nStandards', 'isTarget', 'targetPosition',
                 'standardImage', 'deviantImage', 'standardTargetImage',
                 'deviantTargetImage']
EXTRA_COLS = ['participant', 'seed', 'facesDir']
IMAGE_COLS = ['standardImage', 'deviantImage', 'standardTargetImage',
              'deviantTargetImage']


def fail(message):
    print(f"ERROR: {message}")
    sys.exit(1)


# =============================================================================
# Paths and inputs
# =============================================================================
PROJECT_DIR = Path(__file__).resolve().parent.parent
WORDS_DIR = PROJECT_DIR / 'stimuli' / 'words'


def check_project_root():
    if not (WORDS_DIR / 'death_words.csv').exists():
        fail(f"project root not recognised: {WORDS_DIR / 'death_words.csv'} "
             "does not exist. Keep this script in <project>/conditions/.")


def read_words(path):
    """Word list as in the notebook (pd.read_csv(path)['word'].tolist())."""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "word" not in reader.fieldnames:
            fail(f"{path.name} has no 'word' column")
        words = [row["word"] for row in reader]
    if not words or any(w is None or w.strip() == "" for w in words):
        fail(f"{path.name} is empty or has empty word cells")
    return words


def resolve_faces_dir(faces_dir_arg):
    """faces dir relative to the project root, as a POSIX string."""
    p = Path(faces_dir_arg)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(PROJECT_DIR)
        except ValueError:
            fail(f"--faces-dir must be inside the project: {faces_dir_arg}")
    return p.as_posix().rstrip("/")


def image_paths(faces_rel):
    """Relative POSIX paths, keyed like the notebook's image constants."""
    def rel(name):
        return f"{faces_rel}/{name}"
    return {
        'STD_IMAGE': {'SELF': rel('self.png'), 'OTHER': rel('other.png')},
        'TGT_IMAGE': {'SELF': rel('self_target.png'),
                      'OTHER': rel('other_target.png')},
        'DEV_IMAGE': rel('morph50.png'),
        'DEV_TGT_IMAGE': rel('morph50_target.png'),
    }


def check_face_images(faces_rel):
    """All 6 files must exist; size/mode only warns (needs Pillow)."""
    missing = [n for n in FACE_FILES if not (PROJECT_DIR / faces_rel / n).exists()]
    if missing:
        fail(f"missing face images in {faces_rel}: {missing}")
    try:
        from PIL import Image
    except Exception:
        print(f"[images] all 6 files present in {faces_rel} "
              "(Pillow not installed: size/mode not checked)")
        return
    print(f"[images] all 6 files present in {faces_rel}")
    for n in FACE_FILES:
        with Image.open(PROJECT_DIR / faces_rel / n) as im:
            size, mode = im.size, im.mode
        flag = ""
        if size != EXPECTED_FACE_SIZE or mode != EXPECTED_FACE_MODE:
            flag = (f"   WARNING: expected {EXPECTED_FACE_SIZE[0]}x"
                    f"{EXPECTED_FACE_SIZE[1]} mode {EXPECTED_FACE_MODE}")
        print(f"  {n:20s} {size[0]}x{size[1]} mode={mode}{flag}")


# =============================================================================
# Main table (port of notebook cell 1; same rng call order)
# =============================================================================
def generate_main(seed, death_words, negative_words, imgs):
    rng = random.Random(seed)

    def balanced_split(total, rng):
        base, rem = divmod(total, 4)
        counts = {c: base for c in CONDITIONS}
        if rem == 2:
            for c in rng.choice(DIAGONALS):
                counts[c] += 1
        elif rem != 0:
            for c in rng.sample(CONDITIONS, rem):
                counts[c] += 1
        return counts

    def make_word_cycle(words, n_needed, rng):
        result = []
        while len(result) < n_needed:
            s = words[:]
            rng.shuffle(s)
            result.extend(s)
        return result[:n_needed]

    # --- trial tokens per block (order-shuffled within block) ---
    rows = []
    for block in range(1, N_BLOCKS + 1):
        nt_counts = balanced_split(NONTARGET_PER_BLOCK, rng)
        tg_counts = balanced_split(TARGET_PER_BLOCK, rng)
        tokens = []
        for c in CONDITIONS:
            tokens += [(c, 0)] * nt_counts[c]
            tokens += [(c, 1)] * tg_counts[c]
        rng.shuffle(tokens)
        for j, (cond, is_target) in enumerate(tokens, start=1):
            rows.append({
                'block':          block,
                'trial_in_block': j,
                'condCode':       cond,
                'primeType':      PRIME_MAP[cond],
                'identity':       IDENTITY_MAP[cond],
                'isTarget':       is_target,
            })

    # --- nStandards from a balanced per-condition pool ---
    length_cursor = {c: 0 for c in CONDITIONS}
    length_pool = {}
    for c in CONDITIONS:
        n_c = sum(1 for r in rows if r['condCode'] == c)
        pool = ([3, 4, 5, 6] * (n_c // 4 + 1))[:n_c]
        rng.shuffle(pool)
        length_pool[c] = pool
    for r in rows:
        c = r['condCode']
        r['nStandards'] = length_pool[c][length_cursor[c]]
        length_cursor[c] += 1

    # --- target position: 1..n_std = standard slot, n_std+1 = deviant slot ---
    for r in rows:
        r['targetPosition'] = rng.randint(1, r['nStandards'] + 1) if r['isTarget'] else -1

    # --- words ---
    death_idx = [i for i, r in enumerate(rows) if r['primeType'] == 'DEATH']
    neg_idx = [i for i, r in enumerate(rows) if r['primeType'] == 'NEGATIVE']
    death_cycle = make_word_cycle(death_words, len(death_idx), rng)
    neg_cycle = make_word_cycle(negative_words, len(neg_idx), rng)
    for k, i in enumerate(death_idx):
        rows[i]['word'] = death_cycle[k]
    for k, i in enumerate(neg_idx):
        rows[i]['word'] = neg_cycle[k]

    # --- image columns ---
    for r in rows:
        ident = r['identity']
        r['standardImage'] = imgs['STD_IMAGE'][ident]
        r['deviantImage'] = imgs['DEV_IMAGE']
        r['standardTargetImage'] = imgs['TGT_IMAGE'][ident]
        r['deviantTargetImage'] = imgs['DEV_TGT_IMAGE']
    return rows


# =============================================================================
# Practice table (port of notebook cell 2; Random(99) replaces random.seed(99))
# =============================================================================
def generate_practice(death_words, negative_words, imgs):
    rng = random.Random(PRACTICE_SEED)

    conds = CONDITIONS * 4
    rng.shuffle(conds)
    target_conds = set(rng.sample(CONDITIONS, 4))   # one target per condition
    target_assigned = {c: False for c in CONDITIONS}

    rows = []
    d_idx, n_idx = 0, 0
    for i, cond in enumerate(conds):
        identity = IDENTITY_MAP[cond]
        n_std = rng.randint(3, 6)

        is_target = (not target_assigned[cond]) and (cond in target_conds)
        if is_target:
            target_assigned[cond] = True
            target_pos = rng.randint(1, n_std + 1)
        else:
            target_pos = -1

        if PRIME_MAP[cond] == 'DEATH':
            word = death_words[d_idx % len(death_words)]
            d_idx += 1
        else:
            word = negative_words[n_idx % len(negative_words)]
            n_idx += 1

        rows.append({
            'block': 0,
            'trial_in_block': i + 1,
            'condCode': cond,
            'primeType': PRIME_MAP[cond],
            'identity': identity,
            'word': word,
            'nStandards': n_std,
            'isTarget': int(is_target),
            'targetPosition': target_pos,
            'standardImage': imgs['STD_IMAGE'][identity],
            'deviantImage': imgs['DEV_IMAGE'],
            'standardTargetImage': imgs['TGT_IMAGE'][identity],
            'deviantTargetImage': imgs['DEV_TGT_IMAGE'],
        })
    return rows


def as_strings(rows, participant, seed, faces_rel):
    """Rows as CSV strings with the extra columns appended."""
    out = []
    for r in rows:
        s = {c: str(r[c]) for c in NOTEBOOK_COLS}
        s['participant'] = str(participant)
        s['seed'] = str(seed)
        s['facesDir'] = faces_rel
        out.append(s)
    return out


# =============================================================================
# CSV I/O
# =============================================================================
def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = NOTEBOOK_COLS + EXTRA_COLS
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def read_csv(path):
    if not path.exists():
        fail(f"{path} not found")
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# =============================================================================
# Diagnostics (port of notebook cell 4; numbers only, never Hebrew words)
# =============================================================================
def _int(v):
    return int(float(str(v).strip()))


def _count(rows, key, value):
    return sum(1 for r in rows if r[key] == value)


def _crosstab(rows, row_key, col_key):
    rows_v = sorted({r[row_key] for r in rows}, key=str)
    cols_v = sorted({r[col_key] for r in rows}, key=str)
    table = {rv: {cv: 0 for cv in cols_v} for rv in rows_v}
    for r in rows:
        table[r[row_key]][r[col_key]] += 1
    return rows_v, cols_v, table


def _print_crosstab(rows, row_key, col_key, indent="  "):
    rows_v, cols_v, table = _crosstab(rows, row_key, col_key)
    print(indent + f"{row_key:>10s} | " + " ".join(f"{c:>6}" for c in cols_v)
          + " |  total")
    for rv in rows_v:
        vals = [table[rv][c] for c in cols_v]
        print(indent + f"{rv:>10} | " + " ".join(f"{v:>6}" for v in vals)
              + f" | {sum(vals):>6}")


def _image_path_problems(rows):
    bad = set()
    for r in rows:
        for c in IMAGE_COLS:
            p = Path(r[c])
            full = p if p.is_absolute() else PROJECT_DIR / p
            if not full.exists():
                bad.add(r[c])
    return sorted(bad)


def diagnose_main(rows, death_words, negative_words):
    """Return a list of hard-rule failures (empty = pass)."""
    death_set, neg_set = set(death_words), set(negative_words)
    problems = []
    for r in rows:
        for c in ('block', 'nStandards', 'isTarget', 'targetPosition'):
            r[c] = _int(r[c])
    nt = [r for r in rows if r['isTarget'] == 0]
    tg = [r for r in rows if r['isTarget'] == 1]

    L = "=" * 60
    print(L); print("MAIN TRIAL TABLE DIAGNOSTIC"); print(L)

    print("\n[1] GROSS COUNTS")
    print(f"  total trials      : {len(rows):>4}   (expect 360)")
    print(f"  target trials     : {len(tg):>4}   (expect  90)")
    print(f"  non-target trials : {len(nt):>4}   (expect 270)")
    blocks = sorted({r['block'] for r in rows})
    per_block = {b: sum(1 for r in rows if r['block'] == b) for b in blocks}
    print(f"  trials per block  : {per_block}")
    if len(rows) != 360:
        problems.append(f"total trials {len(rows)} != 360")
    if len(tg) != 90:
        problems.append(f"target trials {len(tg)} != 90")
    if blocks != [1, 2, 3] or any(n != 120 for n in per_block.values()):
        problems.append(f"trials per block {per_block} != 120 x blocks 1-3")

    print("\n[2] CONDITION x TARGET STATUS  (isTarget 0 = non-target, 1 = target)")
    _print_crosstab(rows, 'condCode', 'isTarget')
    print("  NOTE: non-target count per condition = # analyzable MMR sequences per condition")

    print("\n[3] PRIME BALANCE  (death vs negative)")
    for label, sub, expect in [('all', rows, 180), ('non-target', nt, 135),
                               ('target', tg, 45)]:
        d = _count(sub, 'primeType', 'DEATH')
        n = _count(sub, 'primeType', 'NEGATIVE')
        flag = 'OK' if d == n else f'IMBALANCE (diff={d - n:+d})'
        print(f"  {label:<11}: DEATH={d:>4}  NEG={n:>4}   {flag}")
        if label != 'target' and (d != expect or n != expect):
            problems.append(f"PRIME {label} {d}/{n} != {expect}/{expect}")

    print("\n[4] IDENTITY BALANCE  (self vs other)")
    for label, sub, expect in [('all', rows, 180), ('non-target', nt, 135),
                               ('target', tg, 45)]:
        s = _count(sub, 'identity', 'SELF')
        o = _count(sub, 'identity', 'OTHER')
        flag = 'OK' if s == o else f'IMBALANCE (diff={s - o:+d})'
        print(f"  {label:<11}: SELF={s:>4}  OTHER={o:>4}   {flag}")
        if label != 'target' and (s != expect or o != expect):
            problems.append(f"IDENTITY {label} {s}/{o} != {expect}/{expect}")

    print("\n[5] SEQUENCE LENGTH  (nStandards, expect uniform 3-6)")
    dist = {k: sum(1 for r in rows if r['nStandards'] == k)
            for k in sorted({r['nStandards'] for r in rows})}
    dist_nt = {k: sum(1 for r in nt if r['nStandards'] == k)
               for k in sorted({r['nStandards'] for r in nt})}
    print(f"  overall distribution   : {dist}")
    print(f"  non-target distribution: {dist_nt}")
    print("  per condition (mean / min / max / sum):")
    for c in CONDITIONS:
        v = [r['nStandards'] for r in rows if r['condCode'] == c]
        if v:
            print(f"    {c}: {sum(v) / len(v):.2f} / {min(v)} / {max(v)} / {sum(v)}")
    if any(not 3 <= r['nStandards'] <= 6 for r in rows):
        problems.append("nStandards outside 3-6")

    print("\n[6] STANDARD / DEVIANT RATIO  (non-target sequences)")
    n_std = sum(r['nStandards'] for r in nt)
    n_dev = len(nt)
    tot = n_std + n_dev
    if tot:
        print(f"  standards : {n_std:>5}  ({100 * n_std / tot:4.1f}%)")
        print(f"  deviants  : {n_dev:>5}  ({100 * n_dev / tot:4.1f}%)")
    print("  paper reports ~82% / ~18%")

    print("\n[7] TARGET POSITION  (among target trials)")
    if tg:
        at_dev = sum(1 for r in tg if r['targetPosition'] == r['nStandards'] + 1)
        at_std = sum(1 for r in tg if 1 <= r['targetPosition'] <= r['nStandards'])
        pos = [r['targetPosition'] for r in tg]
        print(f"  at a standard slot : {at_std:>3}  ({100 * at_std / len(tg):4.1f}%)")
        print(f"  at the deviant slot: {at_dev:>3}  ({100 * at_dev / len(tg):4.1f}%)")
        print(f"  position range     : {min(pos)}..{max(pos)}")
    bad_pos = [i for i, r in enumerate(rows, start=2)
               if (r['isTarget'] == 1 and not 1 <= r['targetPosition'] <= r['nStandards'] + 1)
               or (r['isTarget'] == 0 and r['targetPosition'] != -1)]
    print(f"  rows with invalid targetPosition: {len(bad_pos)}")
    if bad_pos:
        problems.append(f"targetPosition out of range in CSV lines {bad_pos[:10]}")

    problems += [f"main: {p}" for p in _word_and_image_checks(
        rows, death_set, neg_set, death_words, negative_words, "[8]")]

    print("\n[9] PER-BLOCK CONDITION COUNTS")
    print("  non-target:")
    _print_crosstab(nt, 'block', 'condCode', indent="    ")
    print("  target:")
    _print_crosstab(tg, 'block', 'condCode', indent="    ")
    return problems


def _word_and_image_checks(rows, death_set, neg_set, death_words, negative_words, tag):
    problems = []
    print(f"\n{tag} WORD INTEGRITY & COVERAGE  (words themselves are not printed)")
    empty = [i for i, r in enumerate(rows, start=2) if str(r['word']).strip() == ""]
    d_bad = [i for i, r in enumerate(rows, start=2)
             if r['primeType'] == 'DEATH' and r['word'] not in death_set]
    n_bad = [i for i, r in enumerate(rows, start=2)
             if r['primeType'] == 'NEGATIVE' and r['word'] not in neg_set]
    print(f"  empty word cells                : {len(empty)}")
    print(f"  DEATH trials w/ non-death word  : {len(d_bad)}  CSV lines {d_bad[:10]}")
    print(f"  NEGATIVE trials w/ non-neg word : {len(n_bad)}  CSV lines {n_bad[:10]}")
    for label, wordlist, prime in [('death', death_words, 'DEATH'),
                                   ('negative', negative_words, 'NEGATIVE')]:
        counts = {}
        for r in rows:
            if r['primeType'] == prime:
                counts[r['word']] = counts.get(r['word'], 0) + 1
        if counts:
            lo, hi = min(counts.values()), max(counts.values())
            print(f"  {label:<8}: {len(counts)}/{len(set(wordlist))} unique words used, "
                  f"per-word count min={lo} max={hi}")
    if empty or d_bad or n_bad:
        problems.append("word not in the list of its prime type (or empty)")

    bad_imgs = _image_path_problems(rows)
    print(f"\n{tag[:-1]}b] IMAGE PATHS")
    print(f"  unique image paths: {len({r[c] for r in rows for c in IMAGE_COLS})}, "
          f"missing on this computer: {len(bad_imgs)}")
    for p in bad_imgs:
        print(f"    missing: {p}")
    if bad_imgs:
        problems.append(f"{len(bad_imgs)} image path(s) do not exist")
    return problems


def diagnose_practice(rows, death_words, negative_words):
    problems = []
    for r in rows:
        for c in ('block', 'nStandards', 'isTarget', 'targetPosition'):
            r[c] = _int(r[c])
    L = "=" * 60
    print("\n" + L); print("PRACTICE TABLE DIAGNOSTIC"); print(L)
    tg = [r for r in rows if r['isTarget'] == 1]
    print(f"  total trials : {len(rows)}   (expect 16)")
    print(f"  targets      : {len(tg)}   (expect 4, one per condition)")
    print(f"  block values : {sorted({r['block'] for r in rows})}   (expect [0])")
    print("  condition x target status:")
    _print_crosstab(rows, 'condCode', 'isTarget', indent="    ")
    nstd = {k: sum(1 for r in rows if r['nStandards'] == k)
            for k in sorted({r['nStandards'] for r in rows})}
    print(f"  nStandards distribution: {nstd}")
    print(f"  target positions: {[r['targetPosition'] for r in tg]}")
    if len(rows) != 16:
        problems.append(f"practice trials {len(rows)} != 16")
    for c in CONDITIONS:
        n_c = sum(1 for r in rows if r['condCode'] == c)
        t_c = sum(1 for r in tg if r['condCode'] == c)
        if n_c != 4 or t_c != 1:
            problems.append(f"practice {c}: {n_c} trials / {t_c} targets (expect 4 / 1)")
    if {r['block'] for r in rows} != {0}:
        problems.append("practice block value is not 0")
    if any(not 3 <= r['nStandards'] <= 6 for r in rows):
        problems.append("practice nStandards outside 3-6")
    if any((r['isTarget'] == 1 and not 1 <= r['targetPosition'] <= r['nStandards'] + 1)
           or (r['isTarget'] == 0 and r['targetPosition'] != -1) for r in rows):
        problems.append("practice targetPosition out of range")
    problems += [f"practice: {p}" for p in _word_and_image_checks(
        rows, set(death_words), set(negative_words), death_words, negative_words, "[P]")]
    return problems


def run_diagnostics(main_rows, practice_rows, death_words, negative_words):
    # copies, so the caller's string rows are not converted to ints
    problems = diagnose_main([dict(r) for r in main_rows], death_words, negative_words)
    problems += diagnose_practice([dict(r) for r in practice_rows],
                                  death_words, negative_words)
    print("\n" + "=" * 60)
    if problems:
        print("DIAGNOSTIC RESULT: FAIL")
        for p in problems:
            print(f"  - {p}")
    else:
        print("DIAGNOSTIC RESULT: PASS (all hard rules)")
    print("=" * 60)
    return problems


# =============================================================================
# Main
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate the vMMR trial tables (port of generate_trials.ipynb).")
    ap.add_argument("--participant", type=int, default=None)
    ap.add_argument("--faces-dir", default=DEFAULT_FACES_DIR,
                    help="face-image folder relative to the project root")
    ap.add_argument("--base-seed", type=int, default=DEFAULT_BASE_SEED)
    ap.add_argument("--check-only", action="store_true",
                    help="only run the diagnostics on the existing CSVs")
    ap.add_argument("--overwrite", action="store_true",
                    help="allow replacing existing archive copies")
    # hidden: write main/practice/archive into another folder (testing)
    ap.add_argument("--out-dir", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    check_project_root()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else PROJECT_DIR / "conditions"
    death_words = read_words(WORDS_DIR / 'death_words.csv')
    negative_words = read_words(WORDS_DIR / 'negative_words.csv')
    print(f"Project directory: {PROJECT_DIR}")
    print(f"Output directory : {out_dir}")

    main_path = out_dir / "main_trials.csv"
    practice_path = out_dir / "practice_trials.csv"

    if args.check_only:
        problems = run_diagnostics(read_csv(main_path), read_csv(practice_path),
                                   death_words, negative_words)
        return 1 if problems else 0

    if args.participant is None:
        ap.error("--participant is required unless --check-only is given")
    if args.participant < 0:
        ap.error("--participant must be >= 0")

    seed = args.base_seed + args.participant
    faces_rel = resolve_faces_dir(args.faces_dir)
    print(f"Participant {args.participant}, seed {seed} "
          f"(= base seed {args.base_seed} + participant); faces dir {faces_rel}")

    check_face_images(faces_rel)
    imgs = image_paths(faces_rel)

    main_rows = as_strings(generate_main(seed, death_words, negative_words, imgs),
                           args.participant, seed, faces_rel)
    practice_rows = as_strings(generate_practice(death_words, negative_words, imgs),
                               args.participant, seed, faces_rel)

    archive_dir = out_dir / "generated"
    main_archive = archive_dir / f"main_trials_sub-{args.participant:03d}_seed-{seed}.csv"
    practice_archive = archive_dir / f"practice_trials_sub-{args.participant:03d}.csv"
    existing = [p for p in (main_archive, practice_archive) if p.exists()]
    if existing and not args.overwrite:
        fail("archive file(s) already exist (use --overwrite to replace): "
             + ", ".join(p.name for p in existing))

    problems = run_diagnostics(main_rows, practice_rows, death_words, negative_words)
    if problems:
        print("Nothing written because the diagnostics failed.")
        return 1

    written = []
    for path, rows in [(main_path, main_rows), (practice_path, practice_rows),
                       (main_archive, main_rows), (practice_archive, practice_rows)]:
        write_csv(path, rows)
        written.append(path)
    print("\nWritten files (SHA-256):")
    summary = {}
    for p in written:
        digest = sha256(p)
        summary[str(p)] = digest
        print(f"  {digest}  {p}")
    print("\n" + json.dumps({"participant": args.participant, "seed": seed,
                             "facesDir": faces_rel, "files": summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
