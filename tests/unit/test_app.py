from app import create_app


class TestAppFactory:
    def test_create_app(self):
        """Test that app factory creates a Flask app."""
        app = create_app()

        assert app is not None
        assert app.name == 'app'

    def test_app_has_blueprints(self):
        """Test that app has registered blueprints."""
        app = create_app()

        blueprint_names = [bp.name for bp in app.blueprints.values()]

        assert 'setup' in blueprint_names
        assert 'webhook' in blueprint_names

    def test_app_config(self):
        """Test app configuration."""
        app = create_app()

        assert app.template_folder.endswith('templates')

    def test_index_route(self):
        """Test index route."""
        app = create_app()
        client = app.test_client()
        response = client.get('/')
        assert response.status_code == 200

    def test_robots_txt_route(self):
        """Test robots.txt route."""
        app = create_app()
        client = app.test_client()
        response = client.get('/robots.txt')
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            assert response.mimetype == 'text/plain'

    def test_favicon_route(self):
        """Test favicon.ico route."""
        app = create_app()
        client = app.test_client()
        response = client.get('/favicon.ico')
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            assert 'image' in response.mimetype
