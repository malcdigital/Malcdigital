#include "WebSlingerGameMode.h"

#include "WebSlingerCharacter.h"
#include "WebSlingerHUD.h"

AWebSlingerGameMode::AWebSlingerGameMode()
{
	DefaultPawnClass = AWebSlingerCharacter::StaticClass();
	HUDClass = AWebSlingerHUD::StaticClass();
}
