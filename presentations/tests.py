from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Course
from .models import LessonPlan

User = get_user_model()


class LessonBlueprintEditViewTests(TestCase):
    """Tests for lesson_blueprint_edit view (Task 4.1)"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create instructor user
        self.instructor = User.objects.create_user(
            username='instructor',
            password='testpass123',
            role='instructor'
        )

        # Create course
        self.course = Course.objects.create(
            code='CS101',
            title='Test Course',
            instructor=self.instructor,
            raw_text='Test syllabus content'
        )

        # Create lesson plan with blueprint data
        self.plan_with_blueprint = LessonPlan.objects.create(
            course=self.course,
            topic='Test Topic',
            week_number=1,
            objectives='Test objectives',
            status=LessonPlan.STATUS_BLUEPRINT_PENDING,
            ai_data={
                'blueprint': {
                    'title': 'Test Lesson',
                    'slides': [
                        {
                            'slide_number': 1,
                            'title': 'Introduction',
                            'explanation': 'This is a test explanation for the slide.',
                            'image_prompt': 'test image prompt'
                        }
                    ]
                }
            }
        )
        
        # Create lesson plan without blueprint data
        self.plan_without_blueprint = LessonPlan.objects.create(
            course=self.course,
            topic='Test Topic 2',
            week_number=2,
            objectives='Test objectives 2',
            status=LessonPlan.STATUS_BLUEPRINT_PENDING,
            ai_data={}
        )
        
        # Create lesson plan with wrong status
        self.plan_wrong_status = LessonPlan.objects.create(
            course=self.course,
            topic='Test Topic 3',
            week_number=3,
            objectives='Test objectives 3',
            status=LessonPlan.STATUS_READY,
            ai_data={
                'blueprint': {
                    'title': 'Test Lesson',
                    'slides': []
                }
            }
        )
    
    def test_blueprint_edit_requires_authentication(self):
        """Test that blueprint edit requires authentication"""
        url = reverse('lessons:lesson_blueprint_edit', 
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan_with_blueprint.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_blueprint_edit_requires_instructor_role(self):
        """Test that blueprint edit requires instructor role"""
        # Create non-instructor user
        student = User.objects.create_user(
            username='student',
            password='testpass123',
            is_instructor=False
        )
        self.client.login(username='student', password='testpass123')
        
        url = reverse('lessons:lesson_blueprint_edit',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan_with_blueprint.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)  # Redirect
    
    def test_blueprint_edit_with_valid_blueprint(self):
        """Test blueprint edit view with valid blueprint data"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_blueprint_edit',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan_with_blueprint.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'presentations/blueprint_edit.html')
        self.assertIn('blueprint', response.context)
        self.assertIn('course', response.context)
        self.assertIn('plan', response.context)
        self.assertEqual(response.context['blueprint']['title'], 'Test Lesson')
    
    def test_blueprint_edit_without_blueprint_data(self):
        """Test blueprint edit view handles missing blueprint data gracefully"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_blueprint_edit',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan_without_blueprint.pk})
        response = self.client.get(url)
        
        # Should redirect to lesson_detail
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, 
                           reverse('lessons:lesson_detail',
                                  kwargs={'course_pk': self.course.pk, 'pk': self.plan_without_blueprint.pk}))
    
    def test_blueprint_edit_with_wrong_status(self):
        """Test blueprint edit view validates plan status"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_blueprint_edit',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan_wrong_status.pk})
        response = self.client.get(url)
        
        # Should redirect to lesson_detail with warning
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response,
                           reverse('lessons:lesson_detail',
                                  kwargs={'course_pk': self.course.pk, 'pk': self.plan_wrong_status.pk}))
    
    def test_blueprint_edit_with_failed_status(self):
        """Test blueprint edit view allows editing when status is failed"""
        self.client.login(username='instructor', password='testpass123')
        
        # Update plan status to failed
        self.plan_with_blueprint.status = LessonPlan.STATUS_FAILED
        self.plan_with_blueprint.save()
        
        url = reverse('lessons:lesson_blueprint_edit',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan_with_blueprint.pk})
        response = self.client.get(url)
        
        # Should render the template successfully
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'presentations/blueprint_edit.html')



class LessonBlueprintUpdateViewTests(TestCase):
    """Tests for lesson_blueprint_update AJAX view (Task 4.2)"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create instructor user
        self.instructor = User.objects.create_user(
            username='instructor',
            password='testpass123',
            role='instructor'
        )
        
        # Create course
        self.course = Course.objects.create(
            code='CS101',
            title='Test Course',
            instructor=self.instructor,
            raw_text='Test syllabus content'
        )
        
        # Create lesson plan with blueprint data
        self.plan = LessonPlan.objects.create(
            course=self.course,
            topic='Test Topic',
            week_number=1,
            objectives='Test objectives',
            status=LessonPlan.STATUS_BLUEPRINT_PENDING,
            ai_data={
                'blueprint': {
                    'title': 'Test Lesson',
                    'slides': [
                        {
                            'slide_number': 1,
                            'title': 'Introduction',
                            'explanation': 'This is a test explanation for the slide.',
                            'image_prompt': 'test image prompt'
                        }
                    ],
                    'metadata': {
                        'generated_at': '2024-01-01T00:00:00'
                    }
                }
            }
        )
    
    def test_blueprint_update_requires_authentication(self):
        """Test that blueprint update requires authentication"""
        url = reverse('lessons:lesson_blueprint_update',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan.pk})
        response = self.client.post(url, 
                                   data='{"blueprint": {"slides": []}}',
                                   content_type='application/json')
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_blueprint_update_requires_instructor_role(self):
        """Test that blueprint update requires instructor role"""
        # Create non-instructor user
        student = User.objects.create_user(
            username='student',
            password='testpass123',
            is_instructor=False
        )
        self.client.login(username='student', password='testpass123')
        
        url = reverse('lessons:lesson_blueprint_update',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan.pk})
        response = self.client.post(url,
                                   data='{"blueprint": {"slides": []}}',
                                   content_type='application/json')
        self.assertEqual(response.status_code, 302)  # Redirect
    
    def test_blueprint_update_requires_post(self):
        """Test that blueprint update only accepts POST requests"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_blueprint_update',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 405)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], 'POST required')
    
    def test_blueprint_update_with_valid_data(self):
        """Test blueprint update with valid blueprint data"""
        self.client.login(username='instructor', password='testpass123')
        
        updated_blueprint = {
            'title': 'Updated Lesson',
            'slides': [
                {
                    'slide_number': 1,
                    'title': 'Updated Introduction',
                    'explanation': 'This is an updated explanation for the slide.',
                    'image_prompt': 'updated image prompt'
                },
                {
                    'slide_number': 2,
                    'title': 'New Slide',
                    'explanation': 'This is a new slide added by the teacher.',
                    'image_prompt': 'new slide image'
                }
            ]
        }
        
        url = reverse('lessons:lesson_blueprint_update',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan.pk})
        response = self.client.post(url,
                                   data={'blueprint': updated_blueprint},
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify the blueprint was updated in the database
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.ai_data['blueprint']['title'], 'Updated Lesson')
        self.assertEqual(len(self.plan.ai_data['blueprint']['slides']), 2)
        self.assertEqual(self.plan.ai_data['blueprint']['slides'][0]['title'], 'Updated Introduction')
        
        # Verify edited_at timestamp was added
        self.assertIn('edited_at', self.plan.ai_data['blueprint']['metadata'])
    
    def test_blueprint_update_preserves_metadata(self):
        """Test that blueprint update preserves existing metadata"""
        self.client.login(username='instructor', password='testpass123')
        
        original_generated_at = self.plan.ai_data['blueprint']['metadata']['generated_at']
        
        updated_blueprint = {
            'title': 'Updated Lesson',
            'slides': [
                {
                    'slide_number': 1,
                    'title': 'Updated Introduction',
                    'explanation': 'Updated explanation.',
                    'image_prompt': 'updated prompt'
                }
            ]
        }
        
        url = reverse('lessons:lesson_blueprint_update',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan.pk})
        response = self.client.post(url,
                                   data={'blueprint': updated_blueprint},
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        
        # Verify metadata was preserved and edited_at was added
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.ai_data['blueprint']['metadata']['generated_at'], 
                        original_generated_at)
        self.assertIn('edited_at', self.plan.ai_data['blueprint']['metadata'])
    
    def test_blueprint_update_with_invalid_json(self):
        """Test blueprint update handles invalid JSON"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_blueprint_update',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan.pk})
        response = self.client.post(url,
                                   data='invalid json',
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], 'Invalid JSON')
    
    def test_blueprint_update_with_missing_blueprint_key(self):
        """Test blueprint update validates blueprint structure"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_blueprint_update',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan.pk})
        response = self.client.post(url,
                                   data={'other_key': 'value'},
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], 'Invalid blueprint format')
    
    def test_blueprint_update_with_missing_slides_key(self):
        """Test blueprint update validates slides array exists"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_blueprint_update',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan.pk})
        response = self.client.post(url,
                                   data={'blueprint': {'title': 'Test'}},
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], 'Invalid blueprint format')
    
    def test_blueprint_update_with_non_dict_blueprint(self):
        """Test blueprint update validates blueprint is a dict"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_blueprint_update',
                     kwargs={'course_pk': self.course.pk, 'pk': self.plan.pk})
        response = self.client.post(url,
                                   data={'blueprint': 'not a dict'},
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], 'Invalid blueprint format')
    
    def test_blueprint_update_creates_metadata_if_missing(self):
        """Test that blueprint update creates metadata if it doesn't exist"""
        self.client.login(username='instructor', password='testpass123')
        
        # Create plan without metadata
        plan_no_metadata = LessonPlan.objects.create(
            course=self.course,
            topic='Test Topic 2',
            week_number=2,
            objectives='Test objectives',
            status=LessonPlan.STATUS_BLUEPRINT_PENDING,
            ai_data={
                'blueprint': {
                    'title': 'Test Lesson',
                    'slides': []
                }
            }
        )
        
        updated_blueprint = {
            'title': 'Updated Lesson',
            'slides': [
                {
                    'slide_number': 1,
                    'title': 'Test',
                    'explanation': 'Test explanation.',
                    'image_prompt': 'test'
                }
            ]
        }
        
        url = reverse('lessons:lesson_blueprint_update',
                     kwargs={'course_pk': self.course.pk, 'pk': plan_no_metadata.pk})
        response = self.client.post(url,
                                   data={'blueprint': updated_blueprint},
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        
        # Verify metadata was created with edited_at
        plan_no_metadata.refresh_from_db()
        self.assertIn('metadata', plan_no_metadata.ai_data['blueprint'])
        self.assertIn('edited_at', plan_no_metadata.ai_data['blueprint']['metadata'])



class LessonCreateViewTests(TestCase):
    """Tests for lesson_create view with skip_blueprint parameter (Task 5.1)"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create instructor user
        self.instructor = User.objects.create_user(
            username='instructor',
            password='testpass123',
            role='instructor'
        )
        
        # Create course
        self.course = Course.objects.create(
            code='CS101',
            title='Test Course',
            instructor=self.instructor,
            raw_text='Test syllabus content'
        )
    
    def test_lesson_create_defaults_to_blueprint_mode(self):
        """Test that lesson_create defaults to blueprint mode when skip_blueprint is not provided"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url, {
            'topic': 'Test Lesson',
            'week_number': 1,
            'objectives': 'Test objectives'
        })
        
        # Should redirect to lesson_detail
        self.assertEqual(response.status_code, 302)
        
        # Verify lesson plan was created
        plan = LessonPlan.objects.filter(course=self.course, topic='Test Lesson').first()
        self.assertIsNotNone(plan)
        self.assertEqual(plan.status, LessonPlan.STATUS_PENDING)
    
    def test_lesson_create_with_skip_blueprint_false(self):
        """Test that lesson_create uses blueprint mode when skip_blueprint is false"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url, {
            'topic': 'Test Lesson Blueprint',
            'week_number': 1,
            'objectives': 'Test objectives',
            'skip_blueprint': 'false'
        })
        
        # Should redirect to lesson_detail
        self.assertEqual(response.status_code, 302)
        
        # Verify lesson plan was created
        plan = LessonPlan.objects.filter(course=self.course, topic='Test Lesson Blueprint').first()
        self.assertIsNotNone(plan)
        self.assertEqual(plan.status, LessonPlan.STATUS_PENDING)
    
    def test_lesson_create_with_skip_blueprint_true(self):
        """Test that lesson_create uses direct generation when skip_blueprint is true"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url, {
            'topic': 'Test Lesson Direct',
            'week_number': 1,
            'objectives': 'Test objectives',
            'skip_blueprint': 'true'
        })
        
        # Should redirect to lesson_detail
        self.assertEqual(response.status_code, 302)
        
        # Verify lesson plan was created
        plan = LessonPlan.objects.filter(course=self.course, topic='Test Lesson Direct').first()
        self.assertIsNotNone(plan)
        self.assertEqual(plan.status, LessonPlan.STATUS_PENDING)
    
    def test_lesson_create_with_skip_blueprint_case_insensitive(self):
        """Test that skip_blueprint parameter is case insensitive"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create', kwargs={'course_pk': self.course.pk})
        
        # Test with 'True' (capitalized)
        response = self.client.post(url, {
            'topic': 'Test Lesson Case 1',
            'week_number': 1,
            'objectives': 'Test objectives',
            'skip_blueprint': 'True'
        })
        self.assertEqual(response.status_code, 302)
        
        # Test with 'FALSE' (uppercase)
        response = self.client.post(url, {
            'topic': 'Test Lesson Case 2',
            'week_number': 2,
            'objectives': 'Test objectives',
            'skip_blueprint': 'FALSE'
        })
        self.assertEqual(response.status_code, 302)
        
        # Verify both plans were created
        plan1 = LessonPlan.objects.filter(course=self.course, topic='Test Lesson Case 1').first()
        plan2 = LessonPlan.objects.filter(course=self.course, topic='Test Lesson Case 2').first()
        self.assertIsNotNone(plan1)
        self.assertIsNotNone(plan2)



class LessonCreateFromWeeklyPlanViewTests(TestCase):
    """Tests for lesson_create_from_weekly_plan view with skip_blueprint parameter (Task 5.2)"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create instructor user
        self.instructor = User.objects.create_user(
            username='instructor',
            password='testpass123',
            role='instructor'
        )
        
        # Create course
        self.course = Course.objects.create(
            code='CS101',
            title='Test Course',
            instructor=self.instructor,
            raw_text='Test syllabus content'
        )
    
    def test_lesson_create_from_weekly_plan_defaults_to_blueprint_mode(self):
        """Test that lesson_create_from_weekly_plan defaults to blueprint mode when skip_blueprint is not provided"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create_from_weekly_plan', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url,
                                   data={
                                       'week_number': 1,
                                       'topics': ['Introduction to Programming'],
                                       'cilos': ['Understand basic programming concepts']
                                   },
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('plan_id', data)
        
        # Verify lesson plan was created
        plan = LessonPlan.objects.get(id=data['plan_id'])
        self.assertEqual(plan.course, self.course)
        self.assertEqual(plan.week_number, 1)
        self.assertEqual(plan.topic, 'Introduction to Programming')
        self.assertEqual(plan.status, LessonPlan.STATUS_PENDING)
    
    def test_lesson_create_from_weekly_plan_with_skip_blueprint_false(self):
        """Test that lesson_create_from_weekly_plan uses blueprint mode when skip_blueprint is false"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create_from_weekly_plan', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url,
                                   data={
                                       'week_number': 2,
                                       'topics': ['Data Structures'],
                                       'cilos': ['Understand arrays and lists'],
                                       'skip_blueprint': False
                                   },
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('plan_id', data)
        
        # Verify lesson plan was created
        plan = LessonPlan.objects.get(id=data['plan_id'])
        self.assertEqual(plan.course, self.course)
        self.assertEqual(plan.week_number, 2)
        self.assertEqual(plan.topic, 'Data Structures')
        self.assertEqual(plan.status, LessonPlan.STATUS_PENDING)
    
    def test_lesson_create_from_weekly_plan_with_skip_blueprint_true(self):
        """Test that lesson_create_from_weekly_plan uses direct generation when skip_blueprint is true"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create_from_weekly_plan', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url,
                                   data={
                                       'week_number': 3,
                                       'topics': ['Algorithms'],
                                       'cilos': ['Understand sorting algorithms'],
                                       'skip_blueprint': True
                                   },
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('plan_id', data)
        
        # Verify lesson plan was created
        plan = LessonPlan.objects.get(id=data['plan_id'])
        self.assertEqual(plan.course, self.course)
        self.assertEqual(plan.week_number, 3)
        self.assertEqual(plan.topic, 'Algorithms')
        self.assertEqual(plan.status, LessonPlan.STATUS_PENDING)
    
    def test_lesson_create_from_weekly_plan_requires_authentication(self):
        """Test that lesson_create_from_weekly_plan requires authentication"""
        url = reverse('lessons:lesson_create_from_weekly_plan', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url,
                                   data={
                                       'week_number': 1,
                                       'topics': ['Test'],
                                       'cilos': ['Test']
                                   },
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_lesson_create_from_weekly_plan_requires_instructor_role(self):
        """Test that lesson_create_from_weekly_plan requires instructor role"""
        # Create non-instructor user
        student = User.objects.create_user(
            username='student',
            password='testpass123',
            is_instructor=False
        )
        self.client.login(username='student', password='testpass123')
        
        url = reverse('lessons:lesson_create_from_weekly_plan', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url,
                                   data={
                                       'week_number': 1,
                                       'topics': ['Test'],
                                       'cilos': ['Test']
                                   },
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 302)  # Redirect
    
    def test_lesson_create_from_weekly_plan_requires_post(self):
        """Test that lesson_create_from_weekly_plan only accepts POST requests"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create_from_weekly_plan', kwargs={'course_pk': self.course.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], 'POST required')
    
    def test_lesson_create_from_weekly_plan_requires_week_number(self):
        """Test that lesson_create_from_weekly_plan requires week_number"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create_from_weekly_plan', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url,
                                   data={
                                       'topics': ['Test'],
                                       'cilos': ['Test']
                                   },
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], 'Week number is required')
    
    def test_lesson_create_from_weekly_plan_handles_invalid_json(self):
        """Test that lesson_create_from_weekly_plan handles invalid JSON"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create_from_weekly_plan', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url,
                                   data='invalid json',
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], 'Invalid JSON')
    
    def test_lesson_create_from_weekly_plan_with_empty_topics(self):
        """Test that lesson_create_from_weekly_plan handles empty topics list"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create_from_weekly_plan', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url,
                                   data={
                                       'week_number': 4,
                                       'topics': [],
                                       'cilos': ['Test objective']
                                   },
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify lesson plan was created with generic title
        plan = LessonPlan.objects.get(id=data['plan_id'])
        self.assertEqual(plan.topic, 'Week 4 Lesson')
    
    def test_lesson_create_from_weekly_plan_with_empty_cilos(self):
        """Test that lesson_create_from_weekly_plan handles empty cilos list"""
        self.client.login(username='instructor', password='testpass123')
        
        url = reverse('lessons:lesson_create_from_weekly_plan', kwargs={'course_pk': self.course.pk})
        response = self.client.post(url,
                                   data={
                                       'week_number': 5,
                                       'topics': ['Test Topic'],
                                       'cilos': []
                                   },
                                   content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify lesson plan was created with generic objectives
        plan = LessonPlan.objects.get(id=data['plan_id'])
        self.assertEqual(plan.objectives, 'Course learning outcomes')
