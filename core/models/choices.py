"""Fixed choices shared by models, validation and analytics."""

# "untagged": imported from a LinkedIn export that didn't say what kind of post it was (LinkedIn only
# labels articles and videos). Someone should open the post and pick the real format.
FORMATS = ["image", "carousel", "video", "poll", "newsletter", "text", "untagged"]
FORMAT_CHOICES = [(f, f) for f in FORMATS]

# Hours after publishing at which a performance snapshot is taken
CHECKPOINT_HOURS = {"1h": 1, "6h": 6, "24h": 24, "48h": 48, "7d": 168}
CHECKPOINT_CHOICES = [(c, c) for c in CHECKPOINT_HOURS]

# Each includes the rights of the ones before it. Super admins also manage admins and other super admins.
ROLES = ["viewer", "editor", "admin", "superadmin"]
ROLE_LABELS = {"viewer": "Viewer", "editor": "Editor", "admin": "Admin", "superadmin": "Super admin"}
ROLE_CHOICES = [(r, ROLE_LABELS[r]) for r in ROLES]

PLANNED_STATUSES = ["draft", "approved", "publishing", "published", "failed", "missed"]
# Formats in the publishing queue, and the tracking format each becomes once posted
PLANNED_FORMATS = {"text": "text", "image": "image", "carousel": "carousel", "video": "video", "article": "newsletter", "poll": "poll"}
# The app can publish these itself (personal profiles, "Share on LinkedIn"); the rest are posted by hand for now
AUTO_PUBLISH_FORMATS = {"text", "image"}
