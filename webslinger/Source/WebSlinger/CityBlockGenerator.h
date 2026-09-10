#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "CityBlockGenerator.generated.h"

class UInstancedStaticMeshComponent;
class UStaticMesh;

/**
 * Greybox city built from engine cubes.
 *
 * A swing prototype is untestable in an empty level and there is no way to
 * commit a .umap to a text repository, so the test space is generated instead:
 * drop one of these into a blank level and there is a city to swing through.
 * Instanced, so a few hundred towers cost one draw call each.
 *
 * Deliberately varied in height. A uniform skyline lets any tuning pass, and
 * hides exactly the case that breaks a swing - the anchor that is too low.
 */
UCLASS()
class WEBSLINGER_API ACityBlockGenerator : public AActor
{
	GENERATED_BODY()

public:
	ACityBlockGenerator();

	/** Towers per side. 12 gives roughly a 1km square. */
	UPROPERTY(EditAnywhere, Category = "City", meta = (ClampMin = "1", ClampMax = "40")) int32 GridSize = 12;
	/** Centre-to-centre spacing, cm. */
	UPROPERTY(EditAnywhere, Category = "City") float BlockSpacing = 2600.f;
	UPROPERTY(EditAnywhere, Category = "City") float MinFootprint = 900.f;
	UPROPERTY(EditAnywhere, Category = "City") float MaxFootprint = 1800.f;
	UPROPERTY(EditAnywhere, Category = "City") float MinHeight = 1500.f;
	UPROPERTY(EditAnywhere, Category = "City") float MaxHeight = 9000.f;
	/** Blocks left empty, as a fraction. Gaps are what make a route interesting. */
	UPROPERTY(EditAnywhere, Category = "City", meta = (ClampMin = "0.0", ClampMax = "0.9")) float EmptyBlockChance = 0.12f;
	/** Radius around the origin kept clear so the player start is not inside a wall. */
	UPROPERTY(EditAnywhere, Category = "City") float SpawnClearRadius = 3000.f;
	/** Change for a different skyline; the same seed always rebuilds the same city. */
	UPROPERTY(EditAnywhere, Category = "City") int32 Seed = 20250910;
	UPROPERTY(EditAnywhere, Category = "City") bool bGenerateGround = true;

	virtual void OnConstruction(const FTransform& Transform) override;

	/** Rebuild from the current settings. Called on construction and on load. */
	UFUNCTION(CallInEditor, Category = "City")
	void Generate();

private:
	UPROPERTY(VisibleAnywhere, Category = "City") TObjectPtr<UInstancedStaticMeshComponent> Buildings;
	UPROPERTY(VisibleAnywhere, Category = "City") TObjectPtr<UInstancedStaticMeshComponent> Ground;
};
