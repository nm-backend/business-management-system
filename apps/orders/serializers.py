from rest_framework import serializers
from .models import Order
from apps.warehouse.models import Recipe, RecipeItem, RawMaterial

class OrderSerializer(serializers.ModelSerializer):
    has_material_shortage = serializers.SerializerMethodField()
    client_name = serializers.CharField(source='client.name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    worker_name = serializers.CharField(source='worker.get_full_name', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'client', 'client_name', 'product', 'product_name', 'custom_product_name',
            'quantity', 'unit', 'deadline', 'worker', 'worker_name', 'comment',
            'status', 'payment_status', 'has_material_shortage', 'created_at', 'updated_at'
        ]

    def get_has_material_shortage(self, obj):
        # Strict logic for shortage calculation (Rule 11: Backend checks)
        # 1. Check if product exists and has a recipe
        if not obj.product:
            return False
        
        recipe = Recipe.objects.filter(product=obj.product).first()
        if not recipe:
            return False
        
        # 2. Check each raw material required for the recipe * quantity
        for item in recipe.items.all():
            required_qty = item.quantity * obj.quantity
            material = item.raw_material
            if material.quantity < required_qty:
                return True # Shortage found!
                
        return False
