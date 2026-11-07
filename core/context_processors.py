from .branding import support


def branding(request):
    """The support contacts in every page's footer."""
    return {"support": support()}
