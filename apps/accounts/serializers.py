from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import User

class UserSerializer(serializers.ModelSerializer):
    display_role = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'full_name', 'phone', 'email',
            'role', 'display_role', 'avatar', 'language',
            'is_active', 'can_write_to_owner', 'can_create_workers',
            'can_see_other_workers', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'display_role']

class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = [
            'username', 'password', 'full_name', 'phone', 'email',
            'role', 'language', 'can_write_to_owner',
            'can_create_workers', 'can_see_other_workers',
        ]

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

class UserLimitedSerializer(serializers.ModelSerializer):
    display_role = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'full_name', 'phone',
            'role', 'display_role', 'avatar', 'is_active',
        ]

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()

    def validate(self, data):
        user = authenticate(
            username=data['username'],
            password=data['password']
        )
        if user is None:
            raise serializers.ValidationError('Invalid username or password')
        if not user.is_active:
            raise serializers.ValidationError('Account is deactivated')
        data['user'] = user
        return data

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=6)

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect')
        return value

class SetupOwnerSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=3, max_length=150)
    password = serializers.CharField(write_only=True, min_length=6)
    password_confirm = serializers.CharField(write_only=True)
    full_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=20, required=False, default='')

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match'})
        if User.objects.filter(username=data['username']).exists():
            raise serializers.ValidationError({'username': 'Username already exists'})
        return data

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User(
            username=validated_data['username'],
            full_name=validated_data.get('full_name', ''),
            phone=validated_data.get('phone', ''),
            role=User.Role.OWNER,
            is_staff=True,
            is_superuser=True,
        )
        user.set_password(password)
        user.save()
        return user

class LanguageSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=User.Language.choices)
