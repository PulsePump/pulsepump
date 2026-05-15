{{ fullname | escape | underline}}

.. automodule:: {{ fullname }}

   {% block attributes %}
   {% if attributes %}
   .. rubric:: {{ _('Module attributes') }}

   .. autosummary::
   {% for item in attributes %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block functions %}
   {% if functions %}
   .. rubric:: {{ _('Functions') }}

   .. autosummary::
   {% for item in functions %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block classes %}
   {% if classes %}
   .. rubric:: {{ _('Classes') }}

   .. autosummary::
   {% for item in classes %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block exceptions %}
   {% if exceptions %}
   .. rubric:: {{ _('Exceptions') }}

   .. autosummary::
   {% for item in exceptions %}
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

{% block modules %}
{% set visible_modules = [] %}
{% for item in modules %}
{% set qualified = item if '.' in item else fullname ~ '.' ~ item %}
{% if not (qualified == 'pulsepump.firmware' or qualified.startswith('pulsepump.firmware.')) %}
{% set _ = visible_modules.append(item) %}
{% endif %}
{% endfor %}
{% if visible_modules %}
.. rubric:: Modules

.. autosummary::
   :toctree:
   :recursive:
{% for item in visible_modules %}
   {{ item }}
{%- endfor %}
{% endif %}
{% endblock %}
