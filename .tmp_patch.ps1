$ErrorActionPreference = "Stop"
$path = "praxans_game.py"
$text = Get-Content -Raw -Path $path
$old1 = @"
                except Exception:
                    pass
                    
            # Storyteller Debug Overlay
"@
$new1 = @"
                except Exception as overlay_error:
                    if not debug_watermark_error_logged:
                        game_logger.logger.warning(
                            ""Debug watermark render failed (suppressed after first warning): %s"",
                            overlay_error,
                            exc_info=True,
                        )
                        debug_watermark_error_logged = True
                    
            # Storyteller Debug Overlay
"@
$old2 = @"
                except Exception:
                    pass
            
            # Screen tint for critical overpopulation
"@
$new2 = @"
                except Exception as overlay_error:
                    if not storyteller_overlay_error_logged:
                        game_logger.logger.warning(
                            ""Storyteller overlay render failed (suppressed after first warning): %s"",
                            overlay_error,
                            exc_info=True,
                        )
                        storyteller_overlay_error_logged = True
            
            # Screen tint for critical overpopulation
"@
if (-not $text.Contains($old1)) { throw "old1 block not found" }
if (-not $text.Contains($old2)) { throw "old2 block not found" }
$text = $text.Replace($old1, $new1)
$text = $text.Replace($old2, $new2)
Set-Content -Path $path -Value $text
