from django.urls import path
from django.views.generic import TemplateView

urlpatterns = [
    # Clients are now a JS component in the SPA, so we don't need a separate HTML page 
    # if it's all handled by index.html #/clients hash route. 
    # But just in case, we can provide a dummy or empty list.
]
