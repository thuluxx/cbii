"""Codebase Intelligence Engine: read-only Python repo analyzer (never executes repo code).
Usage: python -m cbi <repo_path> -o report.json"""
import ast, argparse, json, os, subprocess, sys
from collections import Counter
from itertools import combinations
from datetime import date

SKIP = {'.git', 'venv', '.venv', 'env', 'node_modules', '__pycache__', 'build', 'dist', '.tox', '.eggs', 'site-packages'}
BR = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.comprehension, ast.Assert)
STD = getattr(sys, 'stdlib_module_names', set())
clamp = lambda v: max(0, min(100, round(v)))


def cx(n):  # McCabe-style cyclomatic complexity
    c = 1
    for x in ast.walk(n):
        if isinstance(x, BR): c += 1
        elif isinstance(x, ast.BoolOp): c += len(x.values) - 1
    return c


def dotted(p):
    parts = p[:-3].split('/')
    return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)


def parse(root, p):
    src = open(os.path.join(root, p), encoding='utf-8', errors='ignore').read()
    try: t = ast.parse(src)
    except (SyntaxError, ValueError): return None
    fns = [n for n in ast.walk(t) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    cls = [n for n in ast.walk(t) if isinstance(n, ast.ClassDef)]
    loc = sum(1 for l in src.splitlines() if l.strip() and not l.strip().startswith('#'))
    smells, ccs = [], []
    for f in fns:
        c, ln = cx(f), f.end_lineno - f.lineno + 1
        ccs.append(c)
        if ln > 50: smells.append(f'long function {f.name} ({ln} lines)')
        if c > 10: smells.append(f'complex function {f.name} (cc={c})')
        if len(f.args.args) > 5: smells.append(f'many parameters in {f.name}')
    smells += ['bare except' for n in ast.walk(t) if isinstance(n, ast.ExceptHandler) and n.type is None]
    if loc > 500: smells.append(f'large file ({loc} LOC)')
    docs = [ast.get_docstring(n) for n in [t, *fns, *cls]]
    pkg = [x for x in dotted(p).split('.') if x]
    if not p.endswith('__init__.py'): pkg = pkg[:-1]
    imps = []
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            imps += [([a.name], a.name.split('.')[0]) for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            m = n.module or ''
            if n.level:
                b = '.'.join(pkg[:max(0, len(pkg) - n.level + 1)] + ([m] if m else []))
                imps.append(([b + '.' + a.name for a in n.names] + [b], None))
            else:
                imps.append(([m + '.' + a.name for a in n.names] + [m], m.split('.')[0]))
    return dict(path=p, loc=loc, fn=len(fns), cls=len(cls), cx=max(ccs, default=1), cxsum=sum(ccs),
                smells=smells, docs=sum(d is not None for d in docs), doct=len(docs), imps=imps)


def git(root):
    run = lambda *a: subprocess.run(['git', '-C', root, *a], capture_output=True, text=True, check=True).stdout
    try:
        out = run('log', '--relative', '--no-merges', '--date=short', '-n', '3000', '--name-only', '--pretty=format:@@%h|%an|%ad|%s')
        branch = run('rev-parse', '--abbrev-ref', 'HEAD').strip()
    except Exception:
        return None, Counter()
    commits = []
    for blk in out.split('@@')[1:]:
        ls = blk.strip('\n').split('\n')
        h, a, d, s = (ls[0].split('|', 3) + [''] * 4)[:4]
        commits.append((h, a, d, s, [f for f in ls[1:] if f.endswith('.py')]))
    churn = Counter(f for c in commits for f in c[4])
    au = Counter(c[1] for c in commits).most_common()
    co = Counter(p for c in commits if 2 <= len(c[4]) <= 15 for p in combinations(sorted(c[4]), 2))
    mo = sorted(Counter(c[2][:7] for c in commits).items())[-6:]
    top = [list(x) for x in au[:4]]
    if len(au) > 4: top.append(['Others', sum(n for _, n in au[4:])])
    return dict(branch=branch, commits=len(commits), recent=[list(c[:4]) for c in commits[:6]], authors=top,
                monthly=[list(m) for m in mo], cochange=[[a, b, n] for (a, b), n in co.most_common(5)]), churn


def analyze(root):
    root = os.path.abspath(root)
    paths = []
    for d, ds, fs in os.walk(root):
        ds[:] = [x for x in ds if x not in SKIP and not x.startswith('.')]
        paths += [os.path.relpath(os.path.join(d, f), root).replace(os.sep, '/') for f in fs if f.endswith('.py')]
    paths.sort()
    files = [f for f in (parse(root, p) for p in paths) if f]
    mods = {}
    for f in files:
        m = dotted(f['path']); mods[m] = f['path']
        if m.split('.')[0] in ('src', 'lib') and '.' in m: mods[m.split('.', 1)[1]] = f['path']
    edges, ext = set(), Counter()
    for f in files:
        f['ext'] = set()
        for cands, top in f.pop('imps'):
            hit = next((mods['.'.join(c.split('.')[:i])] for c in cands for i in range(len(c.split('.')), 0, -1)
                        if '.'.join(c.split('.')[:i]) in mods), None)
            if hit and hit != f['path']: edges.add((f['path'], hit))
            elif not hit and top and top not in STD: f['ext'].add(top)
        for e in f['ext']: ext[e] += 1
        f['ext'] = sorted(f['ext'])
    fin = Counter(b for _, b in edges)
    g, churn = git(root)
    nfn = sum(f['fn'] for f in files) or 1
    tot = sum(f['loc'] for f in files) or 1
    sm = sum(len(f['smells']) for f in files)
    avg = sum(f['cxsum'] for f in files) / nfn
    docs = 100 * sum(f['docs'] for f in files) / (sum(f['doct'] for f in files) or 1)
    sc = {'Maintainability': clamp(100 - 0.6 * avg * 5 - 20 * sm / nfn * 5), 'Code Smells': clamp(100 - 300 * sm / nfn),
          'Complexity': clamp(100 - 8 * (avg - 1)), 'Documentation': clamp(docs)}
    mi = clamp(.4 * sc['Complexity'] + .3 * sc['Code Smells'] + .3 * sc['Documentation'])
    mx = lambda k: max(k, default=1) or 1
    mc, mch, ms, mf = mx(f['cx'] for f in files), mx(churn.values()), mx(len(f['smells']) for f in files), mx(fin.values())
    hot = []
    for f in files:
        f['churn'], f['fanin'] = churn.get(f['path'], 0), fin.get(f['path'], 0)
        s = .35 * f['cx'] / mc + .30 * f['churn'] / mch + .20 * len(f['smells']) / ms + .15 * f['fanin'] / mf
        why = [f"max function complexity {f['cx']}", f"changed in {f['churn']} commits", f"{len(f['smells'])} code smells",
               f"imported by {f['fanin']} modules"]
        hot.append(dict(path=f['path'], score=round(s, 2), risk='High' if s >= .55 else 'Medium' if s >= .3 else 'Low',
                        cx=f['cx'], churn=f['churn'], why=[w for w, v in zip(why, [f['cx'] > 10, f['churn'], f['smells'], f['fanin']]) if v] or ['no strong signals']))
        f['smells'] = f['smells'][:5]
    hot.sort(key=lambda h: -h['score'])
    for f in files: f.pop('docs'); f.pop('doct')
    return dict(repo=os.path.basename(root), generated=str(date.today()),
                summary=dict(files=len(files), modules=len({os.path.dirname(f['path']) for f in files}), functions=sum(f['fn'] for f in files),
                             classes=sum(f['cls'] for f in files), loc=tot, total_complexity=sum(f['cxsum'] for f in files), avg_complexity=round(avg, 1),
                             smells=sm, mi=mi, mi_label='Good' if mi >= 65 else 'Fair' if mi >= 45 else 'Poor', scores=sc),
                files=files, edges=sorted(edges), ext=ext.most_common(8), git=g, hotspots=hot[:15])


def main():
    ap = argparse.ArgumentParser(prog='cbi', description=__doc__)
    ap.add_argument('repo'); ap.add_argument('-o', '--out', default='report.json')
    a = ap.parse_args()
    if not os.path.isdir(a.repo): sys.exit(f'not a directory: {a.repo}')
    r = analyze(a.repo)
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    json.dump(r, open(a.out, 'w'), separators=(',', ':'))
    print(f"{r['repo']}: {r['summary']['files']} files, {r['summary']['smells']} smells -> {a.out}")
