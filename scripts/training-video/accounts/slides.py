"""Slides for the training video: HTML in Mesiri's look, rendered to 1920x1080 PNGs by Playwright."""

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1280px;height:720px;font-family:Inter,system-ui,sans-serif;background:#fbfaf7;color:#18181b;overflow:hidden;position:relative}
.stripe{position:absolute;top:0;left:0;right:0;height:8px;background:repeating-linear-gradient(135deg,#f5b700 0 14px,#18181b 14px 28px)}
.wrap{padding:64px 80px 120px}
.kicker{font-size:18px;font-weight:600;color:#a16207;letter-spacing:.08em;text-transform:uppercase}
h1{font-size:52px;font-weight:700;letter-spacing:-.02em;margin-top:10px;line-height:1.1}
h2{font-size:40px;font-weight:700;letter-spacing:-.01em;margin-top:8px}
p.lead{font-size:24px;color:#52525b;margin-top:18px;line-height:1.45;max-width:1000px}
.logo{position:absolute;bottom:34px;right:48px;font-weight:800;font-size:22px;color:#18181b}
.logo span{color:#a16207}
.row{display:flex;gap:28px;margin-top:34px}
.card{flex:1;background:#fff;border:1px solid #e4e4e7;border-radius:18px;padding:24px 26px}
.card h3{font-size:22px;font-weight:700;margin-bottom:8px}
.card p{font-size:19px;color:#52525b;line-height:1.4}
.dot{display:inline-block;width:14px;height:14px;border-radius:50%;margin-right:10px;vertical-align:middle}
.sky{background:#0ea5e9}.amber{background:#f59e0b}.violet{background:#8b5cf6}.emerald{background:#10b981}.rose{background:#f43f5e}
table{border-collapse:collapse;width:100%;font-size:22px;margin-top:26px;background:#fff;border-radius:14px;overflow:hidden}
td,th{padding:13px 20px;border-bottom:1px solid #e4e4e7;text-align:left}
th{background:#f4f4f5;font-size:17px;color:#71717a;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
td.n{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
tr.total td{background:#fafaf9;font-weight:700}
.ok{color:#047857}.bad{color:#be123c}.mut{color:#71717a}
.flow{display:flex;align-items:center;gap:16px;margin-top:40px}
.step{background:#fff;border:1px solid #e4e4e7;border-radius:16px;padding:20px 22px;flex:1;min-height:150px}
.step b{display:block;font-size:20px;margin-bottom:6px}.step span{font-size:17px;color:#52525b;line-height:1.35}
.arrow{font-size:34px;color:#a16207}
.big{font-size:30px;font-weight:700;margin-top:30px;text-align:center}
.eq{display:flex;justify-content:center;align-items:center;gap:22px;margin-top:40px;font-size:30px;font-weight:700}
.eq .box{background:#fff;border:2px solid #e4e4e7;border-radius:18px;padding:26px 34px;text-align:center}
.eq .box small{display:block;font-size:17px;font-weight:500;color:#71717a;margin-top:6px}
ul.points{margin-top:28px;list-style:none}
ul.points li{font-size:24px;padding:14px 0 14px 54px;position:relative;border-bottom:1px solid #eee;line-height:1.35}
ul.points li i{position:absolute;left:0;top:12px;width:38px;height:38px;border-radius:12px;background:#fef3c7;color:#a16207;font-style:normal;font-weight:800;text-align:center;line-height:38px}
.chapter{display:flex;flex-direction:column;justify-content:center;height:720px;padding:0 110px;background:#18181b;color:#fff}
.chapter .num{font-size:22px;color:#f5b700;font-weight:700;letter-spacing:.1em}
.chapter h1{font-size:64px;color:#fff}
"""

LOGO = '<div class="logo">mesiri<span>.</span> Accounts</div>'


def page(body: str, dark: bool = False) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{'' if dark else '<div class=stripe></div>'}{body}</body></html>"


def chapter(num: int, title: str) -> str:
    return page(f'<div class="chapter"><div class="num">CHAPTER {num:02d}</div><h1>{title}</h1>'
                f'<div style="margin-top:26px;width:120px;height:6px;background:#f5b700;border-radius:3px"></div></div>', dark=True)


SLIDES = {
    "title": f"""<div class="wrap" style="padding-top:150px"><div class="kicker">Sales team training</div>
      <h1 style="font-size:72px">Mesiri Accounts</h1>
      <p class="lead" style="font-size:28px">The books that keep themselves: what it does, the accounting behind it, and how to sell it.</p>
      <p class="lead mut" style="font-size:20px;margin-top:40px">Malayalam voice · English subtitles · Follow Anjali, a construction company's accountant</p></div>{LOGO}""",
    "problem": f"""<div class="wrap"><div class="kicker">The problem</div><h2>The same bill is typed three times</h2>
      <div class="flow"><div class="step"><b>1 · On site</b><span>Bill photo on WhatsApp, a notebook, an Excel sheet</span></div><div class="arrow">→</div>
      <div class="step"><b>2 · In the office</b><span>Typed again to pay the supplier</span></div><div class="arrow">→</div>
      <div class="step"><b>3 · At the CA</b><span>Typed again into Tally, weeks later</span></div></div>
      <div class="big">Profit is known only after the quarter. <span class="ok">Mesiri: once, on site. Books today.</span></div></div>{LOGO}""",
    "double": f"""<div class="wrap"><div class="kicker">Accounting basics · Double entry</div><h2>Every rupee has two sides</h2>
      <p class="lead">Cement bill from Malabar Steel: ₹11,800 with ₹1,800 GST inside it.</p>
      <table><tr><th>Ledger</th><th style="text-align:right">Debit</th><th style="text-align:right">Credit</th></tr>
      <tr><td><span class="dot rose"></span>Materials (cost)</td><td class="n">₹10,000</td><td></td></tr>
      <tr><td><span class="dot amber"></span>Input GST (we claim it back)</td><td class="n">₹1,800</td><td></td></tr>
      <tr><td style="padding-left:52px"><span class="dot amber"></span>To Malabar Steel (we owe)</td><td></td><td class="n">₹11,800</td></tr>
      <tr class="total"><td>Total · always equal</td><td class="n ok">₹11,800</td><td class="n ok">₹11,800</td></tr></table></div>{LOGO}""",
    "drcr": f"""<div class="wrap"><div class="kicker">Accounting basics</div><h2>Debit and credit, the easy rule</h2>
      <div class="row"><div class="card"><h3>Debit (Dr)</h3><p>What we <b>have</b> or what we <b>spent</b>:<br>bank and cash · clients who owe us · cement, wages, hire</p>
      <p style="margin-top:14px" class="mut">A client's ledger: Dr = he owes us</p></div>
      <div class="card"><h3>Credit (Cr)</h3><p>Where it <b>came from</b> or whom we <b>owe</b>:<br>suppliers to pay · owner's capital · income from RA bills</p>
      <p style="margin-top:14px" class="mut">A supplier's ledger: Cr = we owe him</p></div></div>
      <div class="big">Debits always equal credits.</div></div>{LOGO}""",
    "groups": f"""<div class="wrap"><div class="kicker">Accounting basics · Ledgers and groups</div><h2>Five kinds of account (Tally's groups)</h2>
      <table><tr><th>Kind</th><th>Means</th><th>Examples in a construction company</th></tr>
      <tr><td><span class="dot sky"></span>Assets</td><td>What we own</td><td>Bank, petty cash, client dues, retention held by client</td></tr>
      <tr><td><span class="dot amber"></span>Liabilities</td><td>What we owe</td><td>Suppliers, subcontractors, GST and TDS payable</td></tr>
      <tr><td><span class="dot violet"></span>Capital</td><td>Owner's money</td><td>Capital, profit kept in the business</td></tr>
      <tr><td><span class="dot emerald"></span>Income</td><td>What we earn</td><td>Contract revenue from RA bills</td></tr>
      <tr><td><span class="dot rose"></span>Expenses</td><td>What we spend</td><td>Materials, labour, subcontract, hire, office rent</td></tr></table></div>{LOGO}""",
    "flow": f"""<div class="wrap"><div class="kicker">The magic</div><h2>Entries make themselves</h2>
      <div class="flow"><div class="step"><b>Site</b><span>Bill photo on WhatsApp → expense recorded</span></div><div class="arrow">→</div>
      <div class="step"><b>Finance</b><span>Supplier paid · client pays an RA bill · petty cash topped up</span></div><div class="arrow">→</div>
      <div class="step"><b>Accounts</b><span>Purchase · payment · receipt · contra vouchers, posted on their own</span></div></div>
      <ul class="points"><li><i>✓</i>Subcontract bills with TDS and retention · RA bills with GST, retention, TDS</li>
      <li><i>✓</i>A bill corrected later corrects its entry. Nobody types twice.</li></ul></div>{LOGO}""",
    "pl": f"""<div class="wrap"><div class="kicker">Profit and loss</div><h2>Gross profit, then net profit</h2>
      <table><tr><td>Income (RA bills, before GST)</td><td class="n">₹10,00,000</td></tr>
      <tr><td class="mut">− Direct costs (materials, labour, subcontract, machines)</td><td class="n mut">₹7,00,000</td></tr>
      <tr class="total"><td>= Gross profit · 30%</td><td class="n ok">₹3,00,000</td></tr>
      <tr><td class="mut">− Indirect costs (office rent, salaries)</td><td class="n mut">₹1,00,000</td></tr>
      <tr class="total"><td>= Net profit · 20%</td><td class="n ok">₹2,00,000</td></tr></table></div>{LOGO}""",
    "bs": f"""<div class="wrap"><div class="kicker">Balance sheet</div><h2>A photograph of one day</h2>
      <div class="eq"><div class="box"><span class="dot sky"></span>What we own<small>bank, cash, client dues, retention</small></div><div>=</div>
      <div class="box"><span class="dot amber"></span>What we owe<small>suppliers, GST, TDS</small></div><div>+</div>
      <div class="box"><span class="dot violet"></span>Capital<small>owner's money + profit</small></div></div>
      <div class="big">Both sides always balance.</div></div>{LOGO}""",
    "gst": f"""<div class="wrap"><div class="kicker">GST</div><h2>Pay the difference, claim what you can</h2>
      <div class="eq"><div class="box">Output GST<small>on our RA bills to clients</small></div><div>−</div>
      <div class="box">Input GST<small>on supplier bills, with GSTIN</small></div><div>=</div><div class="box">GST to pay<small>each month (GSTR-3B)</small></div></div>
      <ul class="points"><li><i>!</i>No GSTIN on the supplier's bill → that GST <b class="bad">cannot be claimed</b></li>
      <li><i>⇄</i>Same state (Kerala): half CGST + half SGST · Other state: IGST</li></ul></div>{LOGO}""",
    "tds": f"""<div class="wrap"><div class="kicker">TDS · Section 194C</div><h2>Tax deducted at source</h2>
      <div class="row"><div class="card"><h3>We deduct</h3><p>From a subcontractor's bill: 1% (individual) or 2% (company).<br>Deposit by the <b>7th of next month</b> (March: 30 April). Late = interest.</p></div>
      <div class="card"><h3>Clients deduct</h3><p>From our RA bills. It is <b>our money</b>: claim it against our tax.<br>Match with Form 26AS.</p></div></div></div>{LOGO}""",
    "roles": f"""<div class="wrap"><div class="kicker">Roles</div><h2>Who sees what</h2>
      <table><tr><th>Role</th><th>In Accounts</th></tr>
      <tr><td>Owner · Admin</td><td>Everything, and can reopen a closed month</td></tr>
      <tr><td>Finance (the accountant)</td><td>All books, GST, TDS; closes months</td></tr>
      <tr><td>Project manager</td><td>Only his projects' profit and position</td></tr>
      <tr><td>Site engineer · Supervisor</td><td class="mut">No money; keeps sending updates on WhatsApp</td></tr></table>
      <p class="lead">Accounts is an add-on module, switched on by the Mesiri team.</p></div>{LOGO}""",
    "sell": f"""<div class="wrap"><div class="kicker">How to sell it</div><h2>Four reasons to buy</h2>
      <ul class="points"><li><i>1</i>No double typing: site records become the books</li>
      <li><i>2</i>Profit today, per project, not after the quarter</li>
      <li><i>3</i>GST credit that would be lost, shown every month</li>
      <li><i>4</i>The CA's language: Tally groups, Tally export, Excel</li></ul></div>{LOGO}""",
    "faq": f"""<div class="wrap"><div class="kicker">Objections</div><h2>Questions you will hear</h2>
      <ul class="points"><li><i>?</i><b>"We use Tally."</b> Keep it. Mesiri exports to Tally; nobody retypes.</li>
      <li><i>?</i><b>"Can I trust it?"</b> Every entry must balance; books checked against bank, suppliers, clients.</li>
      <li><i>?</i><b>"My accountant's job?"</b> She stops typing and starts checking.</li>
      <li><i>?</i><b>"Wages?"</b> Booked when paid. Attendance stays in Labour.</li></ul></div>{LOGO}""",
    "recap": f"""<div class="wrap"><div class="kicker">Recap</div><h2>What you now know</h2>
      <ul class="points"><li><i>✓</i>Double entry: debit = credit, always</li>
      <li><i>✓</i>Day book · ledgers · trial balance · P&amp;L · balance sheet · cash &amp; bank</li>
      <li><i>✓</i>Project profit · GST · TDS · month close</li>
      <li><i>✓</i>Roles, selling points, objections</li></ul></div>{LOGO}""",
}
