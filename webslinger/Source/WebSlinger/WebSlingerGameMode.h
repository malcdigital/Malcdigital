#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "WebSlingerGameMode.generated.h"

/** Wires the slinger pawn and HUD to any empty level, with no Blueprint needed. */
UCLASS()
class WEBSLINGER_API AWebSlingerGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AWebSlingerGameMode();
};
