def test_hello_world() -> None:
    """
    A simple hello world test to verify pytest is working.
    """
    assert True

def test_imports() -> None:
    """
    Verify that the main package can be imported.
    """
    import retrylab
    assert retrylab.__version__ == "0.1.0"
    
    from retrylab.cli import app
    assert app is not None
