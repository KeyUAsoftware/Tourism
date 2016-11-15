class ExcursionTypeListView(ListView):
    queryset = ExcursionType.objects.order_by('pk')
    template_name = 'core/excursion-list.html'
    context_object_name = 'excursions'


class ExcursionTypeDetailView(DetailView):
    model = ExcursionType
    template_name = 'core/excursion-detail.html'
    context_object_name = 'excursion'


class ContactCreateView(CreateView):
    model = Contact
    template_name = 'core/contact-create.html'
    fields = ('name', 'email', 'comment', 'phone_number')
    success_url = reverse_lazy('main')

    def form_valid(self, form):
        self.object = contact = form.save()
        contact.ip = self.get_client_ip()
        return super().form_valid(form)

    def get_client_ip(self):
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = self.request.META.get('REMOTE_ADDR')
        return ip


class EmploymentListView(ListView):
    model = Employment
    template_name = 'core/employment-list.html'
    context_object_name = 'employments'


class ExperienceVideoListView(ListView):
    model = ExperienceVideo
    template_name = 'core/experience-video-list.html'
    context_object_name = 'videos'


class ExperienceGalleryListView(ListView):
    model = ExperienceGallery
    template_name = 'core/experience-gallery-list.html'
    context_object_name = 'images'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['videos'] = ExperienceVideo.objects.all()
        return context


class FaqListView(ListView):
    model = FaqCategory
    template_name = 'core/faq-list.html'
    context_object_name = 'faqs'


class AffiliateTemplateView(TemplateView):
    template_name = 'core/affiliate.html'


class BookingWizardView(NamedUrlSessionWizardView):
    template_name = 'booking/booking_wizard_base.html'
    form_list = BOOKING_FORMS
    initial_allowed_fields = ['excursion_type', 'date']

    def dispatch(self, request, *args, **kwargs):
        dispatch = super().dispatch(request, *args, **kwargs)
        if self.steps.current == 'payment' and not self.request.user.is_authenticated():
            self.set_session_before_login()
            return HttpResponseRedirect(reverse('account_signup'))
        if self.steps.current == 'excursion' and not self.get_cleaned_data_for_step('cruise'):
            return self.render_goto_step('cruise')
        return dispatch

    def done(self, form_list, **kwargs):
        data = self.get_all_cleaned_data()
        invoice = Invoice.objects.get(pk=self.storage.data['invoice'])
        if not data.get('cards'):
            CreditCard.objects.authorize_create(self.request.user, data)
        invoice.book = self.create_book(data)
        invoice.save()
        return HttpResponseRedirect(reverse('dashboard'))

    def render_done(self, form, **kwargs):
        render = super().render_done(form, **kwargs)
        if hasattr(form, 'cleaned_data'):
            invoice = Invoice.objects.booking_pay(self.request.user, form.cleaned_data, self.booking_total)
            if not invoice.is_paid:
                form = invoice.authorize_form_errors(form)
                return self.render_revalidation_failure('payment', form, **kwargs)
            self.storage.data['invoice'] = invoice.pk
        return render

    def create_book(self, data):
        data.update({'user': self.request.user, 'is_partner': self.request.user.is_partner})
        for field in ['cruises', 'excursion_type', 'card_holder_name', 'card_number', 'expiration_month',
                      'agrees', 'expiration_year', 'card_code', 'cards']:
            data.pop(field, '')
        return Booking.objects.create(**data)

    def render_revalidation_failure(self, failed_step, form, **kwargs):
        self.storage.current_step = failed_step
        return self.render(form, **kwargs)

    def set_session_before_login(self):
        if not self.request.user.is_authenticated():
            self.request.session['booking_step'] = self.steps.current

    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form, **kwargs)
        cruise_data = self.get_cleaned_data_for_step('cruise')
        if self.steps.current == 'cruise':
            context['excursions_dates'] = Excursion.objects.only('date').filter(date__gte=now().date())
        if self.steps.current == 'excursion' and cruise_data:
            context['excursions_exists'] = Excursion.objects.excursion_filter(
                cruise_data['cruises'], cruise_data['excursion_type'], cruise_data['date'])
        if self.steps.current == 'payment' and self.request.user.is_authenticated():
            context['excursion'] = self.get_cleaned_data_for_step('excursion')['excursion']
            context['booking_description'] = self.booking_description
            context['booking_total'] = self.booking_total
            context['cards'] = CreditCard.objects.filter(user=self.request.user)
        return context

    def get_form_kwargs(self, step=None):
        kwargs = super().get_form_kwargs(step)
        if step == 'payment' and self.request.user.is_authenticated():
            kwargs['cards'] = None
            card = self.request.POST.get('payment-cards')
            if card:
                try:
                    kwargs['cards'] = CreditCard.objects.filter(user=self.request.user, pk=int(card))
                except ValueError:
                    pass
        return kwargs

    def get_template_names(self):
        return [BOOKING_TEMPLATES[self.steps.current]]

    def get_form_initial(self, step):
        initial = super().get_form_initial(step)
        if step == 'cruise':
            for key, value in self.request.GET.items():
                if key in self.initial_allowed_fields:
                    initial[key] = value
        return initial

    @property
    def booking_total(self):
        data = self.get_all_cleaned_data()
        excursion = data['excursion']
        adults_price = excursion.adults_price * int(data['adults'])
        kids_price = excursion.kids_price * int(data['kids'])
        return adults_price + kids_price

    @property
    def booking_description(self):
        data = self.get_all_cleaned_data()
        members = ''
        if int(data['adults']):
            members += '{} adult(s) '.format(data['adults'])
        if int(data['kids']):
            members += '{} kid(s) '.format(data['kids'])
        excursion = data['excursion']
        return 'Booking for {}on {}'.format(members, excursion.string_date_time)


class AjaxCountryRegionsView(JSONResponseMixin, AjaxResponseMixin, View):

    def get(self, request, *args, **kwargs):
        country_pk = request.GET.get('country')
        qs = Region.objects.none()
        if country_pk:
            country = get_object_or_404(Country, pk=country_pk)
            qs = Region.objects.filter(country=country)
        return self.render_json_object_response(qs, fields=('pk', 'name'))