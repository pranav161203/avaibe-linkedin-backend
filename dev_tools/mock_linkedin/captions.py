"""Caption bank for the dummy company page: a UAE software / ERP / edtech firm.

Captions are assembled from a topic's hook, one or two body lines and a call to action, then hashtags,
so 12 months of posts read like a real page without repeating word for word.
Each topic has a relative weight (how often it's posted) and an impression multiplier (how it tends to perform),
both modelled on the patterns seen in a real page's export (e.g. team debate posts outperform, education posts
reach fewer people). Format hints say which formats a topic is usually posted in.
"""

COMPANY = "Demo Tech Solutions"

TOPICS: list[dict] = [
    {
        "name": "Team Tech Debate",
        "weight": 4, "lift": 2.3, "formats": ["video", "image", "poll"],
        "hooks": [
            "THE {a} vs {b} SHOWDOWN IS ON. 🔥",
            "{a} vs {b}: which one would you trust with a real project? 👀",
            "Tech Debate is back! This week: {a} vs {b}.",
            "Two teams. One question. {a} or {b}?",
        ],
        "pairs": [("Copilot", "Cursor"), ("React", "Flutter"), ("Python", "Go"), ("SaaS ERP", "Custom ERP"),
                  ("AWS", "Azure"), ("Agile", "Waterfall"), ("No-code", "Custom code"), ("GPT-6", "Gemini 3")],
        "body": [
            "Our latest team debate brought two squads together to argue it out with real project experience, not hype.",
            "🔹 Team A argued for speed and productivity.\n🔹 Team B argued for control, depth and long-term maintenance.",
            "We recorded the highlights. The winner surprised even our CTO.",
        ],
        "hashtags": ["#TechDebate", "#SoftwareDevelopment", "#Developers", "#AI", "#TeamCulture"],
    },
    {
        "name": "Education & LMS",
        "weight": 5, "lift": 0.65, "formats": ["image", "document", "article"],
        "hooks": [
            "Is your school still managing assignments over WhatsApp and email?",
            "What if every teacher in your school saved 4 hours a week?",
            "Choosing an LMS is about fit, not features.",
            "Parents in the UAE expect real-time updates. Can your school keep up?",
            "AI is changing how students learn. Are schools ready for it?",
        ],
        "body": [
            "A good learning platform brings courses, attendance, assessments and parent communication into one place.",
            "We've seen schools cut admin work in half once their systems finally talk to each other.",
            "The hardest part isn't the software. It's getting teachers to trust it in the first week.",
        ],
        "hashtags": ["#EdTech", "#UAESchools", "#LMS", "#AIinEducation", "#SchoolLeadership"],
    },
    {
        "name": "ERP & CRM",
        "weight": 5, "lift": 0.85, "formats": ["image", "document", "text", "article"],
        "hooks": [
            "Most trading firms don't notice the cracks in their ERP until month-end.",
            "Your sales team and your warehouse are looking at two different versions of the truth.",
            "Off-the-shelf or custom ERP? The honest answer depends on three questions.",
            "VAT season again. Is your ERP doing the work, or are you?",
            "Still exporting to Excel to get a real picture of your business?",
        ],
        "body": [
            "An ERP should connect inventory, finance, sales and VAT reporting, not add another spreadsheet.",
            "We've helped UAE SMEs move from five disconnected tools to one system their teams actually use.",
            "Start with the process that hurts most, not with the biggest module.",
        ],
        "hashtags": ["#ERP", "#CRM", "#UAEBusiness", "#DigitalTransformation", "#SMEs"],
    },
    {
        "name": "Cybersecurity",
        "weight": 4, "lift": 1.05, "formats": ["image", "article", "document"],
        "hooks": [
            "What if your team is already using AI tools that IT never approved?",
            "One phishing email is all it takes.",
            "The GCC is tightening rules on AI security. Here's what changes for businesses.",
            "Backups you've never restored are not backups.",
        ],
        "body": [
            "Shadow AI, weak passwords and unpatched systems remain the biggest risks for SMEs in the region.",
            "Our latest article looks at the new guidelines and what a practical first step looks like.",
            "Security doesn't start with tools. It starts with knowing what you have and who can access it.",
        ],
        "hashtags": ["#Cybersecurity", "#InfoSec", "#AIGovernance", "#UAE", "#SMEs"],
    },
    {
        "name": "AI models & tools",
        "weight": 9, "lift": 1.1, "formats": ["image", "video", "article", "text"],
        "hooks": [
            "A new model just topped the coding benchmarks. Does it matter for real projects?",
            "AI is changing how software gets built. Fast.",
            "We tested the latest AI coding assistant on a real client project. Here's what happened.",
            "The AI race is entering its 'get things done' era.",
            "Agents are everywhere this year. Most of them still need a human in the loop.",
        ],
        "body": [
            "Benchmarks are useful, but what counts is how a tool behaves on a messy, real codebase.",
            "Our developers now use AI daily for tests, reviews and documentation, with clear rules about what never leaves our systems.",
            "The teams that win won't be the ones with the most AI. They'll be the ones who use it with judgement.",
        ],
        "hashtags": ["#AI", "#GenerativeAI", "#AITools", "#SoftwareEngineering", "#FutureOfWork"],
    },
    {
        "name": "AI for business",
        "weight": 3, "lift": 0.8, "formats": ["image", "document"],
        "hooks": [
            "The future of work is AI-powered. But where should a business actually start?",
            "Three AI use cases that pay for themselves in a quarter.",
            "Not every process needs AI. Here's how to tell.",
        ],
        "body": [
            "Start with repetitive work that already has clean data: invoices, support tickets, reports.",
            "Automating one painful workflow beats a dozen pilots that never reach production.",
        ],
        "hashtags": ["#AIforBusiness", "#Automation", "#UAEBusiness", "#Productivity"],
    },
    {
        "name": "UAE trade & economy",
        "weight": 4, "lift": 1.3, "formats": ["article", "image"],
        "hooks": [
            "Dubai just hosted 1,000+ trading professionals. Here's what they were talking about.",
            "The UAE's non-oil trade hit another record. What it means for tech in the region.",
            "Regional trade corridors are shifting. Businesses that adapt early will benefit.",
        ],
        "body": [
            "Our latest newsletter looks at AI-driven trading desks, logistics data and the systems behind them.",
            "Behind every trade flow is a stack of software that needs to keep up.",
        ],
        "hashtags": ["#UAE", "#Dubai", "#Trade", "#CommodityTrading", "#GCC"],
    },
    {
        "name": "UAE AI & innovation",
        "weight": 4, "lift": 0.75, "formats": ["article", "image", "video"],
        "hooks": [
            "The UAE's AI strategy is moving from vision to execution.",
            "Abu Dhabi and Dubai are betting big on AI infrastructure.",
            "What the newest UAE AI initiative means for local businesses.",
        ],
        "body": [
            "This newsletter explores how artificial intelligence and emerging technology are reshaping the region.",
            "For SMEs the opportunity is practical: better data, faster decisions, less manual work.",
        ],
        "hashtags": ["#UAEAI", "#Innovation", "#AI", "#UAE", "#DigitalEconomy"],
    },
    {
        "name": "Websites & digital marketing",
        "weight": 3, "lift": 0.45, "formats": ["image", "text"],
        "hooks": [
            "A visitor lands on your website. What makes them stay or leave? 👀",
            "More visitors won't fix a broken website.",
            "Your website should do more than look good.",
        ],
        "body": [
            "A good website makes your business clear, builds trust and guides visitors to the next step.",
            "Speed, clarity and one obvious call to action beat fancy animations every time.",
        ],
        "hashtags": ["#WebDevelopment", "#WebsiteDesign", "#DigitalMarketing", "#UAE"],
    },
    {
        "name": "Mobile apps",
        "weight": 2, "lift": 0.7, "formats": ["image", "video"],
        "hooks": [
            "Habibi, have an idea for an app? Let's talk about the first version.",
            "Your customers already live on their phones. Does your business?",
        ],
        "body": [
            "Start with the one journey your customers repeat every week and make it effortless.",
            "We build iOS and Android apps for UAE businesses, from first sketch to store launch.",
        ],
        "hashtags": ["#MobileApps", "#AppDevelopment", "#UAE", "#Startups"],
    },
    {
        "name": "Company & culture",
        "weight": 3, "lift": 0.9, "formats": ["image", "video", "text"],
        "hooks": [
            "Ramadan Kareem from all of us at " + COMPANY + ". 🌙",
            "Eid Mubarak! Wishing everyone peace and time with family.",
            "Happy UAE National Day! 🇦🇪",
            "Meet the team behind the code.",
            "Business feeling off track? " + COMPANY + " works alongside you.",
        ],
        "body": [
            "Grateful for our team, our clients and the community that makes this work possible.",
            "We help UAE businesses build software that fits the way they work: ERP, school systems, apps and websites.",
        ],
        "hashtags": ["#TeamCulture", "#UAE", "#LifeAtWork", "#SoftwareCompany"],
    },
]

CTAS = [
    "Which side are you on? Tell us in the comments. 👇",
    "Read the full article in our latest newsletter.",
    "Follow " + COMPANY + " for more practical tech insights.",
    "Want to see how this would work for your business? Send us a message.",
    "What's your experience? Drop it in the comments.",
    "Learn more: www.example-demo.com | hello@example-demo.com",
    "",
]

POLL_QUESTIONS = {
    "Team Tech Debate": ("Which would you pick for your next project?", None),
    "ERP & CRM": ("What slows down your ERP project most?", ["Data migration", "Staff training", "Customisation", "Budget"]),
    "Education & LMS": ("What's the hardest part of running a school system?", ["Parent communication", "Attendance", "Assessments", "Timetables"]),
    "AI models & tools": ("How often does your team use AI tools at work?", ["Daily", "Weekly", "Rarely", "Not allowed"]),
}

ARTICLE_TITLES = {
    "Education & LMS": ["5 signs your school has outgrown its LMS", "AI policies for UAE schools: a practical start"],
    "ERP & CRM": ["Custom vs off-the-shelf ERP for UAE traders", "VAT-ready ERP: a checklist"],
    "Cybersecurity": ["Shadow AI: the risk inside your company", "The GCC's new AI security guidelines, explained"],
    "AI models & tools": ["What this year's AI models mean for software teams", "AI coding assistants in real projects"],
    "UAE trade & economy": ["Inside Dubai's trading boom", "Trade corridors and the tech behind them"],
    "UAE AI & innovation": ["From AI strategy to execution in the UAE", "AI infrastructure in the Gulf"],
}

COMMENTS = {
    "generic": [
        "Great insight!", "Very well explained 👏", "Totally agree with this.", "Thanks for sharing.",
        "This is so relevant right now.", "Interesting perspective.", "Well said!", "Congratulations to the team! 🎉",
        "Useful read, thank you.", "Couldn't agree more.", "Spot on.", "Love this initiative!",
    ],
    "Team Tech Debate": ["Team B all the way!", "Team A had the better arguments 😄", "Great format, do more of these!",
                         "Both have their place honestly.", "Which one won in the end?"],
    "Education & LMS": ["Our school faced exactly this last term.", "Parent communication is the real challenge.",
                        "Would love a demo for our school.", "Teachers need training more than tools."],
    "ERP & CRM": ["Month-end is painful without proper integration.", "Data migration is always the hardest part.",
                  "We moved to a custom ERP last year, no regrets."],
    "Cybersecurity": ["Shadow AI is a real concern.", "Every SME should read this.", "Training is the first line of defence."],
    "AI models & tools": ["Benchmarks vs real life, so true.", "Human in the loop is key.", "Exciting times for developers."],
}
