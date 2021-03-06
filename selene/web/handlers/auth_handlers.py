# -*- coding: utf-8 *-*
import bcrypt
import datetime
import tornado.auth
import tornado.web
import selene.web

from selene import constants, forms, helpers, options as opts
from selene.base import BaseHandler
from tornado.options import options


class RegisterHandler(BaseHandler):

    @selene.web.redirect_authenticated_user
    def get(self):
        self.render("register.html",
            form=forms.RegisterForm(locale_code=self.locale.code))

    @selene.web.redirect_authenticated_user
    def post(self):
        form = forms.RegisterForm(self.request.arguments,
            locale_code=self.locale.code)
        if form.validate():
            if self.db.users.find_one({'email': form.data['email']}):
                self.render('register.html',
                    message=constants.EMAIL_IS_ALREADY_REGISTERED, form=form)
            else:
                user = form.data
                user.update({
                    "password": bcrypt.hashpw(form.data['password'],
                        bcrypt.gensalt()),
                    'enabled': False,
                    'join': datetime.datetime.now(),
                    'join_hash': helpers.generate_md5(),
                    "locale": options.default_language
                })
                self.db.users.insert(user)
                self.smtp.send(constants.CONFIRM_YOUR_ACCOUNT, 'newuser.html',
                    user['email'], {'user': user})
                self.redirect("/login")
        else:
            self.render('register.html', message=form.errors, form=form)


class ConfirmAccountHandler(BaseHandler):

    @selene.web.redirect_authenticated_user
    def get(self, join_hash=None):
        self.db.users.find_and_modify({'join_hash': join_hash},
            {'$unset': {'join_hash': 1}, '$set': {'enabled': True}})
        self.render('confirmaccount.html')


class LoginHandler(BaseHandler):

    @selene.web.redirect_authenticated_user
    def get(self):
        self.render("login.html",
            form=forms.LoginForm(locale_code=self.locale.code,
                next_=self.get_argument('next', '/')))

    @selene.web.redirect_authenticated_user
    def post(self):
        form = forms.LoginForm(self.request.arguments,
            locale_code=self.locale.code)
        if form.validate():
            user = self.db.users.find_one({"email": form.data['email']})
            if user:
                if user['enabled']:
                    pass_check = bcrypt.hashpw(form.data['password'],
                        user["password"]) == user["password"]
                    if pass_check:
                        self.set_secure_cookie("current_user",
                                               user["email"])
                        self.redirect(form.data['next_'] or "/")
                        return
            self.render('login.html',
                message=constants.INCORRECT_USER_PASSWORD, form=form)
        else:
            self.render('login.html', message=form.errors, form=form)


class LoginGoogleHandler(BaseHandler, tornado.auth.GoogleMixin):

    @selene.web.redirect_authenticated_user
    @tornado.web.asynchronous
    def get(self):
        if self.get_argument("openid.mode", None):
            self.next_ = self.get_argument('next', '/')
            self.get_authenticated_user(self.async_callback(self._on_auth))
            return
        self.authenticate_redirect(ax_attrs=['name', 'email', 'language'])

    def _on_auth(self, data):
        if not data:
            raise tornado.web.HTTPError(500)
        user = {
            'name': data['name'],
            'email': data['email'],
            'enabled': True,
            'join': datetime.datetime.now(),
            'locale': data['locale'],
            'accounts': ['google'],
            'google_claimed_id': data['claimed_id']
        }
        self.db.users.update({'email': data['email']}, {'$set': user},
            upsert=True)
        self.set_secure_cookie("current_user", user["email"])
        self.redirect(self.next_)


class LoginTwitterHandler(BaseHandler, tornado.auth.TwitterMixin):

    @selene.web.redirect_authenticated_user
    @tornado.web.asynchronous
    def get(self):
        if self.get_argument("oauth_token", None):
            self.next_ = self.get_argument('next', '/')
            self.get_authenticated_user(self.async_callback(self._on_auth))
            return
        self.authorize_redirect()

    def _on_auth(self, data):
        if not data:
            raise tornado.web.HTTPError(500)
        user = {
            'username': data['username'],
            'name': data['name'],
            'enabled': True,
            'join': datetime.datetime.now(),
            'locale': data['lang'],
            'accounts': ['twitter'],
            'twitter_access_token': data['access_token']
        }
        user_doc = self.db.users.insert(user)
        self.accounts.update({'userid': user_doc['_id'], 'type': 'twitter'},
            data, upsert=True)
        self.set_secure_cookie("current_user", user["username"])
        self.redirect(self.next_)


class AccountHandler(BaseHandler):

    def get(self):
        form = forms.AccountForm(locale_code=self.locale.code,
            language_choices=opts.get_allowed_languages(),
            language=self.get_user_locale().code,
            **self.current_user)
        self.render('account.html', form=form)

    def post(self):
        form = forms.AccountForm(self.request.arguments,
            locale_code=self.locale.code,
            language_choices=opts.get_allowed_languages())
        form.email.process_data(self.current_user['email'])
        if form.validate():
            update = {'$set': {
                'full_name': form.data['full_name'],
                'locale': form.data['language']}}
            if form.data['password']:
                update['$set'].update({'password':
                    bcrypt.hashpw(form.data['password'], bcrypt.gensalt())})
            self.db.users.update({'email': self.current_user['email']}, update)
            self.redirect('/my-account')
        else:
            self.render('account.html', message=form.errors, form=form)


class ChangeLanguageHandler(BaseHandler):

    @selene.web.redirect_authenticated_user
    def post(self):
        form = forms.LanguageForm(self.request.arguments)
        self.set_cookie('locale', form.data['language'])
        self.redirect('/')


class RequestNewPasswordHandler(BaseHandler):

    @selene.web.redirect_authenticated_user
    def get(self):
        self.render('newpassword.html',
            form=forms.RequestNewPasswordForm(locale_code=self.locale.code))

    @selene.web.redirect_authenticated_user
    def post(self):
        form = forms.RequestNewPasswordForm(self.request.arguments,
            locale_code=self.locale.code)
        if form.validate():
            user = self.db.users.find_one({'email': form.data['email']})
            if user:
                reset_hash = helpers.generate_md5()
                user = self.db.users.find_and_modify(
                    {'email': form.data['email']},
                    {'$set': {'reset_hash': reset_hash, 'enabled': True},
                    '$unset': {'join_hash': 1}}, new=True)
                self.smtp.send(constants.RESET_PASSWORD, 'newpassword.html',
                    user["email"], {'user': user})
                self.redirect('/')
                return
            self.render('newpassword.html',
                message=constants.USER_IS_NOT_EXIST, form=form)
        else:
            self.render('newpassword.html', message=form.errors, form=form)


class ResetPasswordHandler(BaseHandler):

    @selene.web.redirect_authenticated_user
    def get(self, reset_hash=''):
        self.render('resetpassword.html',
            form=forms.ResetPasswordForm(reset_hash=reset_hash))

    @selene.web.redirect_authenticated_user
    def post(self, reset_hash=None):
        form = forms.ResetPasswordForm(self.request.arguments,
            locale_code=self.locale.code, reset_hash=reset_hash)
        if form.validate():
            password = bcrypt.hashpw(form.data['password'], bcrypt.gensalt())
            user = self.db.users.find_and_modify({'reset_hash': reset_hash},
                {'$set': {'password': password}}, new=True)
            if user:
                self.smtp.send(constants.UPDATED_PASSWORD,
                    'resetpassword.html', user['email'], {'user': user})
            self.redirect('/login')
        else:
            self.render('resetpassword.html', message=form.errors, form=form)


class LogoutHandler(BaseHandler):

    @tornado.web.authenticated
    def post(self):
        self.clear_cookie("current_user")
        self.redirect("/")
