from mediumlm.urls import normalize_article_url


def test_relative_href_resolves_to_absolute_medium_url():
    assert (
        normalize_article_url("/@janedoe/post-1a2b3c4d5e6f")
        == "https://medium.com/@janedoe/post-1a2b3c4d5e6f"
    )


def test_query_and_fragment_are_stripped():
    assert (
        normalize_article_url("https://medium.com/@a/x-abc123abc123?source=home#frag")
        == "https://medium.com/@a/x-abc123abc123"
    )
