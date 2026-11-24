"""Topic, industry and CTA suggestions from captions."""

from django.test import TestCase

from core.services import topics


class TopicTests(TestCase):
    def test_topics(self):
        self.assertEqual(topics.suggest_topic("Is your school struggling to manage daily tasks? AVAIBE’s LMS helps"), "Education & LMS")
        self.assertEqual(topics.suggest_topic("THE AI CODING SHOWDOWN IS ON. Muse Code 🆚 Claude Code"), "AVAIBE Tech Debate")
        self.assertEqual(topics.suggest_topic("What if your ERP could bring every part of your business together?"), "ERP & CRM")
        # #UAE in the hashtags alone must not make a post "UAE"
        self.assertNotEqual(topics.suggest_topic("A new image model is out. #UAE #Dubai"), "UAE AI & innovation")
        self.assertEqual(topics.hashtags("Hello #Uae #DigitalMarketing"), ["#Uae", "#DigitalMarketing"])
