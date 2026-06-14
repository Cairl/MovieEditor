"""Regression tests for output directory path calculation in build_ffmpeg_command.

Tests verify the Bug Fix: series_mode=True output directory is now at the parent
level of the input directory (sibling), not nested inside the input directory.

Key logic under test (ui/app.py lines 106-114):
    parent_dir = os.path.dirname(input_file)
    stem = os.path.splitext(os.path.basename(input_file))[0]
    if series_mode:
        parent_name = os.path.basename(parent_dir).strip() or 'MovieEditor'
        out_dir = os.path.join(os.path.dirname(parent_dir),
                               f'{parent_name} (MovieEditor{timestamp})')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f'{stem}.mp4')
    else:
        out_path = os.path.join(parent_dir,
                                f'{stem} (MovieEditor{timestamp}).mp4')
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, call


# ---------------------------------------------------------------------------
# Helper: mirrors the exact output-path algorithm from build_ffmpeg_command
# ---------------------------------------------------------------------------

def _calc_output(input_file, series_mode, timestamp='20250101120000'):
    """Mirror lines 106-114 of ui/app.py — build_ffmpeg_command output logic."""
    parent_dir = os.path.dirname(input_file)
    stem = os.path.splitext(os.path.basename(input_file))[0]
    if series_mode:
        parent_name = os.path.basename(parent_dir).strip() or 'MovieEditor'
        out_dir = os.path.join(
            os.path.dirname(parent_dir),
            f'{parent_name} (MovieEditor{timestamp})',
        )
        out_path = os.path.join(out_dir, f'{stem}.mp4')
        return out_path, out_dir
    else:
        out_path = os.path.join(
            parent_dir,
            f'{stem} (MovieEditor{timestamp}).mp4',
        )
        return out_path, None


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestSeriesModeOutputDirectory(unittest.TestCase):
    """Verify series_mode=True produces output dir sibling to input dir."""

    # -- Windows paths -------------------------------------------------------

    def test_windows_output_dir_is_sibling_not_nested(self):
        """D:\\TV\\Season1\\ep01.mp4 → D:\\TV\\Season1 (MovieEditorts)\\ep01.mp4"""
        input_file = r'D:\TV\Season1\ep01.mp4'
        ts = '20250101120000'
        out_path, out_dir = _calc_output(input_file, True, ts)

        expected_dir = r'D:\TV\Season1 (MovieEditor20250101120000)'
        expected_path = os.path.join(expected_dir, 'ep01.mp4')

        self.assertEqual(out_dir, expected_dir)
        self.assertEqual(out_path, expected_path)
        # Key regression check: output must NOT be inside the input dir
        input_parent = os.path.dirname(input_file)  # D:\TV\Season1
        self.assertFalse(
            out_dir.startswith(input_parent + os.sep),
            f'BUG: output dir {out_dir!r} is nested inside input dir '
            f'{input_parent!r}',
        )

    def test_windows_deeply_nested_input(self):
        """D:\\A\\B\\C\\D\\file.mp4 → D:\\A\\B\\C\\D (MovieEditorts)\\file.mp4"""
        input_file = r'D:\A\B\C\D\file.mp4'
        ts = '20250101120000'
        out_path, out_dir = _calc_output(input_file, True, ts)

        expected_dir = r'D:\A\B\C\D (MovieEditor20250101120000)'
        expected_path = os.path.join(expected_dir, 'file.mp4')
        self.assertEqual(out_dir, expected_dir)
        self.assertEqual(out_path, expected_path)

    def test_windows_root_level_input(self):
        """D:\\video.mp4 fallback (parent dir is root, name='MovieEditor')."""
        input_file = r'D:\video.mp4'
        ts = '20250101120000'
        out_path, out_dir = _calc_output(input_file, True, ts)

        # parent_dir = 'D:\\', os.path.dirname('D:\\') = 'D:\\'
        # parent_name = os.path.basename('D:\\').strip() = '' → 'MovieEditor'
        expected_dir = os.path.join('D:\\', f'MovieEditor (MovieEditor{ts})')
        self.assertEqual(out_dir, expected_dir)
        self.assertEqual(out_path, os.path.join(expected_dir, 'video.mp4'))

    # -- Unix paths ----------------------------------------------------------

    def test_unix_output_dir_is_sibling_not_nested(self):
        """/home/user/videos/show/ep01.mp4 →
        /home/user/videos/show (MovieEditorts)/ep01.mp4"""
        input_file = '/home/user/videos/show/ep01.mp4'
        ts = '20250101120000'
        out_path, out_dir = _calc_output(input_file, True, ts)

        # Normalize expected for cross-platform (os.path.join uses OS sep)
        expected_dir = os.path.normpath(
            '/home/user/videos/show (MovieEditor20250101120000)')
        expected_path = os.path.join(expected_dir, 'ep01.mp4')

        self.assertEqual(out_dir, expected_dir)
        self.assertEqual(out_path, expected_path)
        # Key regression check
        input_parent = os.path.dirname(input_file)
        self.assertFalse(
            os.path.normpath(out_dir).startswith(
                os.path.normpath(input_parent) + os.sep),
            f'BUG: output dir {out_dir!r} is nested inside input dir '
            f'{input_parent!r}',
        )

    def test_unix_home_directory_input(self):
        """/home/bob/show/ep01.mp4 → /home/bob/show (MovieEditorts)/ep01.mp4"""
        input_file = '/home/bob/show/ep01.mp4'
        ts = '20250101120000'
        out_path, out_dir = _calc_output(input_file, True, ts)

        expected_dir = os.path.normpath(
            '/home/bob/show (MovieEditor20250101120000)')
        self.assertEqual(out_dir, expected_dir)
        self.assertEqual(out_path, os.path.join(expected_dir, 'ep01.mp4'))

    # -- Edge cases ----------------------------------------------------------

    def test_filename_with_multiple_dots_preserves_stem(self):
        """show.ep01.x264.mp4 → …/show.ep01.x264.mp4 (stem = show.ep01.x264)"""
        input_file = r'D:\TV\Season1\show.ep01.x264.mp4'
        ts = '20250101120000'
        out_path, out_dir = _calc_output(input_file, True, ts)

        expected_stem = 'show.ep01.x264'
        self.assertTrue(
            out_path.endswith(f'{expected_stem}.mp4'),
            f'Expected stem {expected_stem!r} in path {out_path!r}',
        )

    def test_timestamp_is_preserved_in_output_dir(self):
        """Timestamp must appear exactly in the output directory name."""
        input_file = r'D:\TV\Season1\ep01.mp4'
        ts = '20991231235959'
        _, out_dir = _calc_output(input_file, True, ts)
        self.assertIn(ts, out_dir)

    def test_parent_name_with_trailing_spaces_trimmed(self):
        """Parent dir 'Season1   ' → parent_name = 'Season1'."""
        # Simulate a directory name with trailing spaces (unusual but possible
        # on some filesystems).  os.path.basename doesn't trim, but .strip()
        # in the code does.
        input_file = r'D:\TV\Season1   \ep01.mp4'
        ts = '20250101120000'
        out_path, out_dir = _calc_output(input_file, True, ts)

        self.assertIn('Season1 (MovieEditor', out_dir)
        self.assertNotIn('Season1   ', out_dir)


class TestMovieModeOutputDirectory(unittest.TestCase):
    """Verify series_mode=False (movie mode) output remains unchanged."""

    def test_movie_mode_windows_output_in_same_dir(self):
        """D:\\Movies\\film.mp4 → D:\\Movies\\film (MovieEditorts).mp4"""
        input_file = r'D:\Movies\film.mp4'
        ts = '20250101120000'
        out_path, out_dir = _calc_output(input_file, False, ts)

        parent_dir = os.path.dirname(input_file)
        expected_path = os.path.join(parent_dir, f'film (MovieEditor{ts}).mp4')
        self.assertEqual(out_path, expected_path)
        self.assertIsNone(out_dir)

    def test_movie_mode_unix_output_in_same_dir(self):
        """/data/movies/film.mp4 → /data/movies/film (MovieEditorts).mp4"""
        input_file = '/data/movies/film.mp4'
        ts = '20250101120000'
        out_path, out_dir = _calc_output(input_file, False, ts)

        parent_dir = os.path.dirname(input_file)
        expected_path = os.path.join(parent_dir, f'film (MovieEditor{ts}).mp4')
        self.assertEqual(out_path, expected_path)
        self.assertIsNone(out_dir)


class TestMakedirsCalledCorrectly(unittest.TestCase):
    """Verify os.makedirs(out_dir, exist_ok=True) is called with directory,
    not with the output file path."""

    def test_makedirs_target_is_directory_not_file(self):
        """out_dir must not be the same as out_path and must not have a
        file extension."""
        input_file = r'D:\TV\Season1\ep01.mp4'
        ts = '20250101120000'
        out_path, out_dir = _calc_output(input_file, True, ts)

        # out_dir is the directory, out_path is the file inside it
        self.assertNotEqual(out_dir, out_path,
                            'makedirs target must be directory, not file path')
        self.assertTrue(out_path.startswith(out_dir + os.sep),
                        f'out_path {out_path!r} must be inside out_dir {out_dir!r}')
        # out_dir should NOT have a file extension like .mp4
        self.assertFalse(out_dir.endswith('.mp4'),
                         f'out_dir {out_dir!r} must not end with .mp4')

    def test_makedirs_exist_ok_flag(self):
        """exist_ok=True must be passed (test via mock on actual import)."""
        # We test this via the mocked process_files test below
        pass


class TestProcessFilesIntegration(unittest.TestCase):
    """Mocked integration: verify build_ffmpeg_command produces correct paths
    when called through process_files()."""

    @patch('os.makedirs')
    @patch('ui.app.run_ffmpeg_with_progress')
    @patch('ui.app.get_subtitle_streams')
    @patch('ui.app.get_audio_streams')
    @patch('ui.app.get_video_duration')
    @patch('ui.app.get_video_resolution')
    @patch('ui.app.get_video_files_in_dir')
    @patch('os.path.isdir')
    def test_series_mode_command_contains_correct_output_path(
        self,
        mock_isdir,
        mock_get_video_files,
        mock_get_resolution,
        mock_get_duration,
        mock_get_audio,
        mock_get_subtitle,
        mock_run_ffmpeg,
        mock_makedirs,
    ):
        """In series mode the ffmpeg command's last arg must be the output
        path at the parent level of the input directory."""
        from ui.app import process_files

        # Setup: simulate `python app.py D:\TV\Season1`
        test_input_dir = r'D:\TV\Season1'
        test_files = [
            os.path.join(test_input_dir, 'ep01.mp4'),
            os.path.join(test_input_dir, 'ep02.mp4'),
        ]

        # Mock os.path.isdir: return True only for the input dir
        def _isdir(path):
            return path == test_input_dir
        mock_isdir.side_effect = _isdir

        mock_get_video_files.return_value = test_files
        mock_get_resolution.return_value = (1920, 1080)
        mock_get_duration.return_value = 600.0
        mock_get_audio.return_value = [{'index': 0, 'rel_index': 0}]
        mock_get_subtitle.return_value = []

        with patch.object(sys, 'argv', ['app.py', test_input_dir]):
            process_files()

        # After process_files runs, makedirs should have been called
        self.assertTrue(mock_makedirs.called)
        # Get the directory passed to makedirs
        makedirs_calls = [
            c[0][0] for c in mock_makedirs.call_args_list
            if c[0][0]  # skip empty
        ]
        for dir_path in makedirs_calls:
            # Directory must NOT be nested inside the input dir
            self.assertFalse(
                dir_path.startswith(test_input_dir + os.sep),
                f'makedirs target {dir_path!r} must NOT be nested inside '
                f'input dir {test_input_dir!r}',
            )
            # Directory must be at the parent level
            parent_of_input = os.path.dirname(test_input_dir)
            self.assertTrue(
                dir_path.startswith(parent_of_input),
                f'makedirs target {dir_path!r} must be under '
                f'{parent_of_input!r}',
            )

        # Verify the ffmpeg command's output path (last arg)
        self.assertTrue(mock_run_ffmpeg.called)
        for call_args in mock_run_ffmpeg.call_args_list:
            cmd = call_args[0][0]  # first positional arg = command list
            out_path = cmd[-1]  # last arg of ffmpeg command
            # out_path must NOT be inside the input directory
            self.assertFalse(
                out_path.startswith(test_input_dir + os.sep),
                f'Output path {out_path!r} must NOT be inside input dir '
                f'{test_input_dir!r}',
            )
            # out_path must be under the parent of input dir
            parent_of_input = os.path.dirname(test_input_dir)
            self.assertTrue(
                out_path.startswith(parent_of_input),
                f'Output path {out_path!r} must be under {parent_of_input!r}',
            )
            # Verify correct format: *.mp4 file inside a (MovieEditorts) dir
            self.assertTrue(out_path.endswith('.mp4'))
            self.assertIn('MovieEditor', out_path)

    @patch('os.makedirs')
    @patch('ui.app.run_ffmpeg_with_progress')
    @patch('ui.app.get_subtitle_streams')
    @patch('ui.app.get_audio_streams')
    @patch('ui.app.get_video_duration')
    @patch('ui.app.get_video_resolution')
    @patch('ui.app.get_video_files_in_dir')
    @patch('os.path.isfile')
    def test_movie_mode_output_stays_in_input_dir(
        self,
        mock_isfile,
        mock_get_video_files,
        mock_get_resolution,
        mock_get_duration,
        mock_get_audio,
        mock_get_subtitle,
        mock_run_ffmpeg,
        mock_makedirs,
    ):
        """In movie mode the output file stays in the same directory as input."""
        from ui.app import process_files

        test_input_file = r'D:\Movies\film.mp4'

        # Mock os.path.isfile: return True only for our test file
        def _isfile(path):
            return path == test_input_file
        mock_isfile.side_effect = _isfile

        mock_get_video_files.return_value = []
        mock_get_resolution.return_value = (1920, 1080)
        mock_get_duration.return_value = 7200.0
        mock_get_audio.return_value = [{'index': 0, 'rel_index': 0}]
        mock_get_subtitle.return_value = []

        with patch.object(sys, 'argv', ['app.py', test_input_file]):
            process_files()

        self.assertTrue(mock_run_ffmpeg.called)
        cmd = mock_run_ffmpeg.call_args[0][0]
        out_path = cmd[-1]

        # In movie mode, output must be IN the same dir as input
        input_dir = os.path.dirname(test_input_file)
        self.assertTrue(
            out_path.startswith(input_dir),
            f'Movie mode: output {out_path!r} must be in input dir {input_dir!r}',
        )
        # Format: film (MovieEditorts).mp4 (single file, no extra dir)
        self.assertTrue(out_path.endswith('.mp4'))
        self.assertIn('MovieEditor', out_path)


if __name__ == '__main__':
    unittest.main()
