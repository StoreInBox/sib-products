# coding: utf-8
from __future__ import unicode_literals

from django.core.exceptions import ValidationError
from django.db import models
from django.template.defaultfilters import slugify
from django.utils.translation import ugettext_lazy as _
from django.utils.encoding import python_2_unicode_compatible
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFit
from model_utils import FieldTracker
from model_utils.models import TimeStampedModel
from unidecode import unidecode

from . import settings


@python_2_unicode_compatible
class Characteristic(models.Model):
    """ Abstract product attribute.

    Characteristic is connected to category. All products that are
    connected to category with characteristic must have attribute that
    defines concrete value of given characteristic.
    """
    class Meta:
        verbose_name = _('Characteristic')
        verbose_name_plural = _('Characteristics')

    category = models.ForeignKey('Category', related_name='characteristics')
    name = models.CharField(_('Name'), max_length=255)

    def __str__(self):
        return 'Characteristic %s for category %s' % (self.name, self.category)


@python_2_unicode_compatible
class Category(models.Model):
    """ Category model. Each category can have several children categories. """
    class Meta:
        verbose_name = _('Category')
        verbose_name_plural = _('Categories')
        ordering = ['order_number']

    name = models.CharField(_('Name'), max_length=255)
    slug = models.SlugField(
        _('Slug'), max_length=255,
        help_text=_('This field will be shown in URL address (for SEO). It will be filled automatically.'))
    parent = models.ForeignKey('Category', related_name='children', null=True)
    image = models.ImageField(upload_to='categories/', verbose_name=_('Category'), null=True)
    order_number = models.PositiveIntegerField(default=0)

    def __str__(self):
        return '{}'.format(self.name)

    @classmethod
    def get_top_categories(cls):
        """ Get categories that do not have parents """
        return cls.objects.filter(parent__isnull=True)

    def get_siblings(self):
        """ Get all categories that have the same parent as this """
        if self.parent is None:
            return Category.get_top_categories().exclude(id=self.id)
        else:
            return Category.objects.filter(parent=self.parent).exclude(id=self.id)

    def get_ancestors(self):
        """ Get all categories that have selected category as descendant """
        if self.parent is not None:
            yield self.parent
            for ancestor in self.parent.get_ancestors():
                yield ancestor

    def get_descendants(self):
        """ Get all categories that have selected category as ancestor """
        for child in self.children.all():
            yield child
            for childs_descendant in child.get_descendants():
                yield childs_descendant

    def get_products(self):
        """ Get all products that are related to this category or its descendants """
        descendants = set(self.get_descendants())
        descendants.add(self)
        return Product.objects.filter(category__in=descendants)

    def get_all_characteristics(self):
        """ Get all characteristic that are related to category or any of its ancestors """
        characteristics = list(self.characteristics.all())
        for ancestor in self.get_ancestors():
            characteristics += list(self.parent.characteristics.all())
        return characteristics

    def clean(self):
        # category slug has to be unique for same level categories
        self.slug = slugify(unidecode(self.name))
        if self.get_siblings().filter(slug=self.slug).exists():
            raise ValidationError(
                _('Category with same name already exists on the same level. Please choose another name.'))

    def save(self, *args, **kwargs):
        self.slug = slugify(unidecode(self.name))
        return super(Category, self).save(*args, **kwargs)


@python_2_unicode_compatible
class Product(TimeStampedModel):
    """ Product model """
    class Meta:
        verbose_name = _('Product')
        verbose_name_plural = _('Products')

    name = models.CharField(_('Name'), max_length=255, unique=True)
    slug = models.SlugField(
        _('Slug'), max_length=255, unique=True,
        help_text=_('This field will be shown in URL address (for SEO). It will be filled automatically.'))
    code = models.CharField(_('Code'), max_length=127, unique=True)
    brand = models.CharField(_('Brand'), max_length=255, blank=True)
    category = models.ForeignKey(Category, related_name='products')
    short_description = models.CharField(
        _('Product short description'), max_length=1023, blank=True,
        help_text=_('This description will be shown on page with products list.'))
    description = models.TextField(_('Product description'), blank=True)
    is_active = models.BooleanField(
        _('Is product active'), default=True,
        help_text=_('Non-active products is not visible for users.'))
    price = models.DecimalField(_('Price'), max_digits=16, decimal_places=2)

    tracker = FieldTracker()

    def __str__(self):
        return '{}'.format(self.name)

    def get_main_image(self):
        return self.images.filter(is_main=True).first()

    def _get_all_attributes(self):
        """ Get list of attributes that product already have and attributes that was predefined by user """
        return list(self.attributes.all()) + list(getattr(self, 'predefined_attributes', []))

    def clean(self):
        # Product category can be changed only to child category
        if self.id is not None:
            previous_category = Product.objects.get(id=self.id).category
            if previous_category != self.category and self.category not in previous_category.get_descendants():
                raise ValidationError(_('Product category can be changed only to child category'))
        # Product module expects "predefined_attributes" field to be defined explicitly
        category_characteristics = set(self.category.get_all_characteristics())
        attributes_characteristics = set([attr.characteristic for attr in self._get_all_attributes()])
        required_characteristics = category_characteristics - attributes_characteristics
        if required_characteristics:
            raise ValidationError(
                _('Attributes for characteristics: {} has to defined')
                .format(', '.join(c.name for c in required_characteristics)))

    def save(self, *args, **kwargs):
        self.slug = slugify(unidecode(self.name))
        saved = super(Product, self).save(*args, **kwargs)
        for attribute in getattr(self, 'predefined_attributes', []):
            attribute.product = self
            attribute.save()
        return saved


@python_2_unicode_compatible
class ProductAttribute(models.Model):
    characteristic = models.ForeignKey(Characteristic, related_name='attributes', null=True, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name='attributes')
    name = models.CharField(_('Name'), max_length=255, blank=True)
    value = models.CharField(_('Value'), max_length=31, blank=True)
    value_float = models.FloatField(
        _('Attribute value as number'), null=True,
        help_text=_('This field will be defined automatically'))

    def __str__(self):
        return '{}'.format(self.name)

    def get_display_name(self):
        """
        Return name of attribute that has to be shown to user

        If product attribute is connected to characteristic - return characteristic name,
        return own attribute name otherwise
        """
        if self.characteristic:
            return self.characteristic.name
        return self.name

    def clean(self):
        if self.characteristic and self.name:
            raise ValidationError(_('Product attribute can not have name if it is connected to characteristic.'))
        if not self.characteristic and not self.name:
            raise ValidationError(_('Characteristic or name has to be defined for product attribute.'))

    def save(self, *args, **kwargs):
        try:
            self.value_float = float(self.value)
        except ValueError:
            pass
        return super(ProductAttribute, self).save(*args, **kwargs)


@python_2_unicode_compatible
class ProductImage(models.Model):
    class Meta:
        verbose_name = _('Product image')
        verbose_name_plural = _('Product images')

    product = models.ForeignKey(Product, related_name='images')
    image = models.ImageField(upload_to='products/', verbose_name=_('Image'))
    image_small_thumbnail = ImageSpecField(
        source='image',
        processors=[ResizeToFit(width=settings.SMALL_THUMBNAIL_WIDTH, height=settings.SMALL_THUMBNAIL_HEIGHT,
                                upscale=True, mat_color='white')],
        format='JPEG',
        options={'quality': 100})
    image_big_thumbnail = ImageSpecField(
        source='image',
        processors=[ResizeToFit(width=settings.BIG_THUMBNAIL_WIDTH, height=settings.BIG_THUMBNAIL_HEIGHT,
                                upscale=True, mat_color='white')],
        format='JPEG',
        options={'quality': 100})
    description = models.CharField(_('Image description'), max_length=127, blank=True)
    is_main = models.BooleanField(
        default=True,
        help_text=_('If image is main - it will be displayed on product list page'))

    def __str__(self):
        return 'Image for product {} ({})'.format(self.product.name, self.description)
