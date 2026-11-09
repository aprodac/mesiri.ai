"""Mesiri Accounts: training video for the sales team. Each scene: a chapter title, and lines.

A line is (subtitle, shot) or (subtitle, shot, say): ``subtitle`` is the English shown on screen, ``say`` the English
sent for the Malayalam voice when it should differ (numbers in words), ``shot`` what is on screen from that line on
(None: keep the last). A shot is a slide ("slide:<name>") or a dashboard page {"url", "hl": [texts to highlight],
"click": [texts to click first], "keys": [...], "scroll": text}.
"""

P = "7b62f766-aba7-437f-b399-9e75b57a1e9c"  # Villa Kakkanad, the demo project

SCENES = [
    ("Mesiri Accounts", [
        ("Welcome. This video teaches you Mesiri Accounts: what it does, the accounting behind it, and how to sell it.", "slide:title"),
        ("By the end, you will be able to sit with a builder and his accountant and answer every question with confidence.", None),
        ("We will follow Anjali, the accountant of a construction company, through her day in Mesiri.", None),
    ]),
    ("The problem we solve", [
        ("Today, a builder's site team records expenses on WhatsApp, in notebooks and in Excel.", "slide:problem"),
        ("Then an accountant types the same bills again into Tally, weeks later.", None),
        ("So the owner sees his profit only when the CA sends the quarter's figures. By then it is too late to act.", None),
        ("Mesiri Accounts removes that retyping. Every bill, payment and client receipt already in Mesiri becomes an accounting entry on its own.", None),
        ("The owner sees cash, profit and what is owed today, not next quarter. That is our promise.", None),
    ]),
    ("Accounting in five minutes: two sides", [
        ("First, a little accounting. Every rupee has two sides: where it came from, and where it went.", "slide:double"),
        ("This is called double entry. One side is the debit, the other is the credit. They are always equal.", None),
        ("Example: a cement bill of ₹11,800 from Malabar Steel, with ₹1,800 GST inside it.", None,
         "Example: a cement bill of eleven thousand eight hundred rupees from Malabar Steel, with one thousand eight hundred rupees GST inside it."),
        ("Materials gets a debit of ₹10,000. Input GST gets a debit of ₹1,800. Malabar gets a credit of ₹11,800, because we owe them.", None,
         "Materials gets a debit of ten thousand. Input GST gets a debit of one thousand eight hundred. Malabar gets a credit of eleven thousand eight hundred, because we owe them."),
        ("Debits ₹11,800, credits ₹11,800. Equal. Mesiri checks this on every single entry, and refuses one that does not balance.", None,
         "Debits eleven thousand eight hundred, credits eleven thousand eight hundred. Equal. Mesiri checks this on every single entry, and refuses one that does not balance."),
    ]),
    ("Debit and credit, the easy rule", [
        ("An easy way to remember debit and credit.", "slide:drcr"),
        ("Debit is what the company has, or what it spent: cash in the bank, money clients owe us, cement, wages.", None),
        ("Credit is where it came from, or whom we owe: suppliers we must pay, the owner's capital, the income from bills to clients.", None),
        ("So a supplier's ledger normally shows a credit balance: that is what we owe him. A client's ledger shows a debit: that is what he owes us.", None),
    ]),
    ("Ledgers and groups", [
        ("Each account is called a ledger. Every supplier, every client, every bank account and every expense head has its own ledger.", "slide:groups"),
        ("Ledgers sit in groups. Mesiri uses the same groups as Tally, so the CA feels at home.", None),
        ("Five kinds: assets, what we own. Liabilities, what we owe. Capital, the owner's money. Income. And expenses.", None),
        ("Remember these five colours. You will see them on every screen of Mesiri Accounts.", None),
    ]),
    ("Anjali's home screen", [
        ("Now, the software. Anjali logs in as the accountant. Her role is Finance.", {"url": "/accounts"}),
        ("Her home screen answers the owner's four questions at once: how much cash do we have, who owes us, whom do we owe, and are we making profit.", {"url": "/accounts", "hl": ["Cash & bank today", "Clients owe us", "We owe suppliers & staff"]}),
        ("Profit this month is compared with last month, with an arrow up or down.", {"url": "/accounts", "hl": ["Profit this month"]}),
        ("The chart shows the whole financial year, April to March, month by month. Green bars are profit, red bars are loss. Tap a month for its figures.", {"url": "/accounts", "hl": ["month by month"]}),
        ("On the right: each bank and cash account, the GST to pay this month, and the TDS to deposit.", {"url": "/accounts", "hl": ["GST payable this month", "TDS to deposit"]}),
        ("And at the top, a list for the accountant: things that need her attention, like money received with no client set.", {"url": "/accounts", "hl": ["For the accountant"]}),
    ]),
    ("Where the entries come from", [
        ("Here is the magic, and your strongest selling point. Anjali did not type any of this.", "slide:flow"),
        ("A site engineer sends a bill photo on WhatsApp. Mesiri reads it and records the expense.", None),
        ("The moment it is confirmed, Accounts posts a purchase entry: materials and GST debited, the supplier credited.", None),
        ("When finance pays the supplier, a payment entry. When the client pays an RA bill, a receipt entry. Transfers to site petty cash, a contra entry.", None),
        ("Subcontractor bills with TDS and retention, client RA bills with GST, retention and TDS, all of them, automatically.", None),
        ("If a bill is corrected later, the entry corrects itself. Nobody types anything twice.", None),
    ]),
    ("The day book", [
        ("The day book is every entry, day by day. Accountants call each entry a voucher.", {"url": "/accounts/day-book?range=fy"}),
        ("Six kinds of voucher, each with its own colour and icon: purchase, payment, receipt, sales, contra and journal.", {"url": "/accounts/day-book?range=fy", "hl": ["Purchase", "Payment", "Receipt", "Sales", "Contra", "Journal"]}),
        ("Each day shows the money that came in and went out. She can search a supplier, a number, or any word.", {"url": "/accounts/day-book?range=fy&q=Malabar"}),
        ("She opens a voucher with a tap, or with the arrow keys and Enter, like Tally.", {"url": "/accounts/day-book?range=fy&q=Malabar", "keys": ["ArrowDown", "Enter"]}),
        ("Every voucher shows its debits and credits, the project and site, and a button that opens the original bill with its photo.", None),
        ("This is what makes the CA trust it: every figure traces back to the record it came from.", None),
    ]),
    ("Ledgers: party statements", [
        ("Every ledger has its statement. Here is Malabar Steel, a supplier.", {"url": "/accounts/ledgers?kind=vendor"}),
        ("Each line says what it was against: 'By' for what we owe him, 'To' for what we paid. And a running balance after every line.", {"url": "__malabar__", "hl": ["Particulars", "Balance"]}),
        ("The line on top shows how the balance moved over the period.", {"url": "__malabar__", "hl": ["Balance over the period"]}),
        ("The closing balance, a credit, is what we still owe Malabar. It matches the supplier page in Finance exactly.", {"url": "__malabar__", "hl": ["Closing"]}),
        ("Any ledger can be downloaded to Excel and sent to the supplier or the client. No more arguments over who owes what.", None),
    ]),
    ("The trial balance", [
        ("The trial balance lists every ledger's balance. The total debits must equal the total credits.", {"url": "/accounts/trial-balance"}),
        ("The green badge at the top says it: balanced.", {"url": "/accounts/trial-balance", "hl": ["Balanced"]}),
        ("Groups open to show their ledgers, coloured by their kind, with a bar showing their size.", {"url": "/accounts/trial-balance", "hl": ["Ledgers by group"]}),
        ("Mesiri also checks the books against the other modules: every bank account against Finance, every supplier against the supplier ledger, every client against Receivables.", {"url": "/accounts/trial-balance", "hl": ["differs from its module"]}),
        ("If anything differs, it says so and shows which one. It never hides a difference.", None),
        ("The trial balance works for the whole company, one project or one site, using the selector at the top.", None),
    ]),
    ("Chart of accounts", [
        ("The chart of accounts is the list of all groups and ledgers.", {"url": "/accounts/chart"}),
        ("It comes ready, with Tally's groups and the ledgers a builder needs: contract revenue, GST, TDS, retention, mobilisation advance.", {"url": "/accounts/chart", "hl": ["Retention receivable", "TDS receivable"]}),
        ("Each supplier, client, bank account and expense head gets its ledger on its own, the first time it is used. Nothing to set up.", None),
        ("The accountant can still add ledgers, rename them, or move them to another group, the way her CA likes it.", None),
    ]),
    ("Profit and loss", [
        ("The profit and loss statement. First, the idea.", "slide:pl"),
        ("Income is what we billed clients, before GST. Direct costs are what the work itself cost: materials, labour, subcontractors, machines.", None),
        ("Income minus direct costs is the gross profit. Then subtract the office costs, the indirect expenses, and you get the net profit.", None),
        ("In Mesiri, it reads exactly like that, with the margin as a percentage.", {"url": "/accounts/pl?range=fy"}),
        ("She can compare with the period before, or the same period last year. Arrows show what went up or down.", {"url": "/accounts/pl?range=fy", "hl": ["Period before", "Last year"]}),
        ("Tap a group to see its ledgers, and a ledger to see its entries.", None),
    ]),
    ("The balance sheet", [
        ("The balance sheet is a photograph of one day: what the company owns, against what it owes plus the owner's capital.", "slide:bs"),
        ("Both sides must be equal. That is why it is called a balance sheet.", None),
        ("Mesiri shows the two sides next to each other, for any date, with this year's profit added to capital.", {"url": "/accounts/balance-sheet", "hl": ["Balances", "Capital and liabilities", "Assets"]}),
    ]),
    ("Cash and bank", [
        ("Cash and bank shows every bank account and site petty cash box: opening, money in, money out, closing.", {"url": "/accounts/cash-bank?range=fy"}),
        ("The chart shows each day's money in and out. Moves between our own accounts are left out, so it shows real money only.", {"url": "/accounts/cash-bank?range=fy", "hl": ["Money in", "Money out"]}),
        ("The balances are the same as the Money page in Finance, to the rupee.", None),
    ]),
    ("Which site makes money", [
        ("This is the screen owners love: which project makes money.", {"url": "/accounts/projects?range=fy"}),
        ("For every project: billed, cost, profit and margin, and what the client owes and what we owe for it.", {"url": "/accounts/projects?range=fy", "hl": ["Villa Kakkanad"]}),
        ("Open a project and you see its position: billed, received, still owed, retention the client is holding, TDS the client deducted.", {"url": f"/accounts/projects/{P}?range=fy", "hl": ["Position today"]}),
        ("Where the cost went, by cost centre: materials, labour, subcontract, machines.", {"url": f"/accounts/projects/{P}?range=fy", "hl": ["Where the cost went"]}),
        ("And the BOQ budget from Cost Control right beside the books. If the forecast goes over the budget, it says so in red.", {"url": f"/accounts/projects/{P}?range=fy", "hl": ["Against the BOQ budget"]}),
        ("A project manager can see his own project's books, but never the company's.", None),
        ("If the owner wants, office costs like rent and salaries can be shared over the projects each month, so each project's profit is after its share.", {"as": "admin", "url": "/accounts/projects?range=fy", "scroll": "Head-office costs in project profit", "hl": ["Head-office costs in project profit"]}),
    ]),
    ("GST, explained", [
        ("Now GST. Every builder worries about it, so learn this well.", "slide:gst"),
        ("Output GST is the GST we charge clients on RA bills. Input GST is the GST we paid on purchases.", None),
        ("We pay the government output minus input. Input GST we can deduct is called input tax credit.", None),
        ("But input credit is allowed only if the supplier has a GSTIN on the bill. A bill from a supplier with no GSTIN: that GST is lost.", None),
        ("Within Kerala, GST is split half CGST and half SGST. With a party in another state, it is IGST.", None),
    ]),
    ("GST in Mesiri", [
        ("Mesiri's GST page gives the month's figures in the return's own terms, ready for the CA.", {"url": "/accounts/gst?range=fy"}),
        ("Output GST, input GST we can claim, and the net to pay, split into IGST, CGST and SGST.", {"url": "/accounts/gst?range=fy", "hl": ["Output GST (on RA bills)", "Input GST you can claim", "Net GST payable"]}),
        ("And the credit missed: bills whose GST cannot be claimed, and why. Usually, the supplier's GSTIN is missing.", {"url": "/accounts/gst?range=fy", "hl": ["Credit missed"]}),
        ("Tell the customer this: Mesiri shows the money you are losing on GST every month, while there is still time to fix it. That alone can pay for Mesiri.", None),
        ("The green badge says the GST figures agree with the books. And everything downloads to Excel for the CA.", {"url": "/accounts/gst?range=fy", "hl": ["Agrees with the books", "Excel"]}),
    ]),
    ("TDS, explained", [
        ("TDS means tax deducted at source. When we pay a subcontractor, the law says we keep back a small part, one or two percent, under section 194C.", "slide:tds"),
        ("That money belongs to the government. It must be deposited by the 7th of the next month. Late means interest.", None),
        ("Clients do the same to us: they deduct TDS from our RA bills. That TDS is ours to claim against our tax.", None),
    ]),
    ("TDS in Mesiri", [
        ("Mesiri deducts TDS when a subcontractor's bill is checked, and keeps it in a TDS payable account.", {"url": "/accounts/tds?range=fy"}),
        ("The TDS page shows each month: deducted, deposited, still to deposit, and the due date. Late months turn red.", {"url": "/accounts/tds?range=fy", "hl": ["Month by month", "Late"]}),
        ("It lists each subcontractor with his PAN, and the TDS clients deducted from our bills, to match with Form 26AS.", {"url": "/accounts/tds?range=fy", "hl": ["By subcontractor", "Deducted by clients from our RA bills"]}),
    ]),
    ("Closing the month", [
        ("Once the CA has checked a month, Anjali closes it. Closed months are locked.", {"url": "/accounts/periods"}),
        ("If a bill from a closed month is changed later, the site is never blocked. The difference is posted on the first open day, and marked as changed after close.", {"url": "/accounts/periods", "hl": ["css:[aria-label=\"Months of the year\"]"]}),
        ("Only the owner or an admin can reopen a month, and they must give a reason. This is the control accountants and auditors look for.", None),
    ]),
    ("Who sees what", [
        ("Know the roles. The owner, admins and finance see the books.", "slide:roles"),
        ("A project manager sees only his own projects' profit and position.", None),
        ("Site engineers and supervisors never see money in the books. They just keep sending their updates on WhatsApp.", None),
        ("Accounts is an add-on module. The Mesiri team switches it on for a company.", None),
    ]),
    ("How to sell it", [
        ("Now, how to sell it. Four points.", "slide:sell"),
        ("One: no double typing. Site records become the books on their own. The accountant reviews instead of retyping.", None),
        ("Two: profit today, per project, not after the quarter.", None),
        ("Three: GST credit that would have been lost is shown every month.", None),
        ("Four: it speaks the CA's language, Tally's groups, Tally export and Excel, so the CA is your friend, not your enemy.", None),
    ]),
    ("Questions customers ask", [
        ("Questions you will hear.", "slide:faq"),
        ("'We already use Tally.' Answer: keep it. Mesiri keeps the books from the site, and exports vouchers to Tally for the CA. No retyping.", None),
        ("'Can I trust the numbers?' Answer: every entry must balance, or it is refused. And the books are checked against bank, suppliers and clients every time.", None),
        ("'Will my accountant lose her job?' Answer: no. She stops typing and starts checking. Her work becomes more valuable.", None),
        ("'What about wages?' Answer: wages enter the books when they are paid. Attendance stays in the Labour module.", None),
    ]),
    ("Summary", [
        ("Let's recap. Every rupee has two sides, debit and credit, always equal.", "slide:recap"),
        ("Mesiri turns site records into the books automatically: day book, ledgers, trial balance, profit and loss, balance sheet, cash and bank.", None),
        ("Project profit, GST and TDS are ready every month, and the CA gets Excel and Tally.", None),
        ("You now know more accounting than most of our customers. Go and sell it with confidence. Thank you.", None),
    ]),
]
