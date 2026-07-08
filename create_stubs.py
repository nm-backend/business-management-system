import os
stub_apps = ['warehouse', 'orders', 'production', 'clients', 'finance', 'messaging', 'reports', 'audit']
base_dir = r'c:\Users\User\Documents\GitHub\business-management-system\apps'

for app in stub_apps:
    app_dir = os.path.join(base_dir, app)
    os.makedirs(app_dir, exist_ok=True)
    
    with open(os.path.join(app_dir, '__init__.py'), 'w') as f:
        f.write('"""' + app.capitalize() + ' app."""\n')
        
    with open(os.path.join(app_dir, 'apps.py'), 'w') as f:
        f.write('from django.apps import AppConfig\n\n')
        f.write('class ' + app.capitalize() + 'Config(AppConfig):\n')
        f.write('    default_auto_field = \'django.db.models.BigAutoField\'\n')
        f.write('    name = \'apps.' + app + '\'\n')
        f.write('    verbose_name = \'' + app.capitalize() + '\'\n')
        
    with open(os.path.join(app_dir, 'models.py'), 'w') as f:
        f.write('"""' + app.capitalize() + ' models."""\n')
        
    with open(os.path.join(app_dir, 'views.py'), 'w') as f:
        f.write('"""' + app.capitalize() + ' views."""\n')
        
    with open(os.path.join(app_dir, 'urls.py'), 'w') as f:
        f.write('urlpatterns = []\n')
        
    with open(os.path.join(app_dir, 'serializers.py'), 'w') as f:
        f.write('"""' + app.capitalize() + ' serializers."""\n')
        
    with open(os.path.join(app_dir, 'admin.py'), 'w') as f:
        f.write('"""' + app.capitalize() + ' admin."""\n')
