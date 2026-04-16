/* TinyMCE WYSIWYG initialisation for template body */
(function () {
  var bodyField = document.getElementById('body');
  if (!bodyField) return;

  var isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';

  tinymce.init({
    target: bodyField,
    license_key: 'gpl',
    promotion: false,
    branding: false,
    height: 480,
    menubar: 'file edit view insert format table',
    plugins: 'advlist autolink lists link image charmap preview anchor searchreplace visualblocks code fullscreen insertdatetime media table help wordcount',
    toolbar: 'undo redo | blocks fontfamily fontsize | bold italic underline strikethrough | forecolor backcolor | alignleft aligncenter alignright alignjustify | bullist numlist outdent indent | link image table | code fullscreen | removeformat help',
    content_css: isDark ? 'dark' : 'default',
    skin: isDark ? 'oxide-dark' : 'oxide',
    convert_urls: false,
    entity_encoding: 'raw',
    valid_elements: '*[*]',
    extended_valid_elements: 'style[*]',
    custom_elements: '~style',
    valid_children: '+body[style]',
    setup: function (editor) {
      editor.on('change keyup', function () {
        editor.save();
      });
    }
  });
})();
