"""Mock LinkedIn API routes: /mock-linkedin/rest/<same path as https://api.linkedin.com/rest/…>"""

from django.urls import path

from dev_tools.mock_linkedin import server as s

urlpatterns = [
    path("rest/organizationalEntityShareStatistics", s.share_statistics),
    path("rest/organizationalEntityFollowerStatistics", s.follower_statistics),
    path("rest/organizationPageStatistics", s.page_statistics),
    path("rest/networkSizes/<path:urn>", s.network_sizes),
    path("rest/organizations", s.organizations),
    path("rest/organizations/<str:org_id>", s.organizations),
    path("rest/organizationsLookup", s.organizations_lookup),
    path("rest/posts", s.posts),
    path("rest/posts/<path:urn>", s.post_detail),
    path("rest/socialActions/<path:urn>/comments", s.comments),
    path("rest/reactions/<path:entity>", s.reactions),
    path("rest/socialMetadata", s.social_metadata),
    path("rest/socialMetadata/<path:urn>", s.social_metadata),
    path("rest/videoAnalytics", s.video_analytics),
    path("rest/memberCreatorPostAnalytics", s.member_post_analytics),
    path("rest/memberCreatorVideoAnalytics", s.member_video_analytics),
    path("rest/memberFollowersCount", s.member_followers),
    path("rest/organizationalEntityNotifications", s.notifications),
    path("rest/geo", s.lookup_all, {"kind": "geo"}),
    path("rest/functions", s.lookup_all, {"kind": "functions"}),
    path("rest/seniorities", s.lookup_all, {"kind": "seniorities"}),
    path("rest/industryTaxonomyVersions/DEFAULT/industries", s.lookup_all, {"kind": "industries"}),
    path("rest/geo/<str:item_id>", s.lookup, {"kind": "geo"}),
    path("rest/functions/<str:item_id>", s.lookup, {"kind": "functions"}),
    path("rest/seniorities/<str:item_id>", s.lookup, {"kind": "seniorities"}),
    path("rest/industryTaxonomyVersions/DEFAULT/industries/<str:item_id>", s.lookup, {"kind": "industries"}),
    path("_usage", s.usage),
]
